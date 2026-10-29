"""delegate / recall / quota through the MCP server. Everything external is mocked:
no network, no Meta API, no real Codex logs."""
import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest

from compute_mint.delegate import TEMPLATES, DelegateConfig, Delegator, HttpUpstream
from compute_mint.labels import Label
from compute_mint.ledger import Ledger
from compute_mint.mcp_server import build_server
from compute_mint.memory import Memory
from compute_mint.origin import Origin
from compute_mint.quota import read_codex_quota
from compute_mint.sources import PublicFetcher, SourceError, check_public_url, html_to_text

FIXTURES = Path(__file__).parent / "fixtures" / "codex_home"
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
PAGE = f"<html><head><style>x{{}}</style></head><body><h1>Release notes</h1><p>Fixed bug 42.</p>" \
       f"<script>alert(1)</script><p>Contact ops@acme-corp.io about {KEY}</p></body></html>"


class FakeUpstream:
    def __init__(self):
        self.calls: list[tuple[str, list[dict]]] = []

    async def __call__(self, model, messages):
        self.calls.append((model, messages))
        seen = json.dumps(messages, ensure_ascii=False)
        content = "Summary: bug 42 fixed." + (" ⟨EMAIL_1⟩ was mentioned." if "⟨EMAIL_1⟩" in seen else "")
        return {"choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 2000, "completion_tokens": 100}}


def public_transport(requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/hop":
            return httpx.Response(302, headers={"location": "http://10.0.0.5/admin"})
        if request.url.path == "/bin":
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"\x00\x01")
        if request.url.path == "/missing":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGE)
    return httpx.MockTransport(handler)


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "public"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "notes.md").write_text("Public changelog: version 2 ships Friday.", encoding="utf-8")
    (root / ".secret").mkdir()
    (root / ".secret" / "x.md").write_text("hidden", encoding="utf-8")
    (tmp_path / "private.txt").write_text("PRIVATE-FILE-TEXT", encoding="utf-8")
    requests: list[httpx.Request] = []

    async def search(q: str) -> str:
        return f"Result A about {q}\nResult B about {q}"

    fetcher = PublicFetcher(root, search_fn=search, transport=public_transport(requests),
                            resolver=lambda host: ["93.184.216.34"])
    upstream = FakeUpstream()
    ledger = Ledger()
    cfg = DelegateConfig(api_base="https://mock/v1", api_key="t", caller=Origin.ANTHROPIC, public_root=str(root), billing="paid")
    return fetcher, upstream, ledger, Delegator(fetcher, upstream, cfg, ledger), requests, tmp_path


def unwrap(result):
    """FastMCP returns (content, structured) for typed results and a content list for plain dicts."""
    return result[1] if isinstance(result, tuple) else json.loads(result[0].text)


def run(coro):
    return asyncio.run(coro)


# ---- delegate ----

def test_url_summary_goes_to_contributor_with_clean_masked_prompt(env):
    _, upstream, ledger, d, requests, _ = env
    out = run(d.delegate("summarize", ["https://example.org/release"]))
    assert out["lane"] == "contributor" and out["model"] == "muse-spark-1.3-contributor"
    model, sent = upstream.calls[0]
    assert model == "muse-spark-1.3-contributor"
    assert [m["role"] for m in sent] == ["system", "user"] and sent[0]["content"] == TEMPLATES["summarize"]
    blob = json.dumps(sent, ensure_ascii=False)
    assert "Fixed bug 42" in blob and "alert(1)" not in blob and "<h1>" not in blob
    assert KEY not in blob and "ops@acme-corp.io" not in blob          # FLOOR spans masked before leaving
    assert "https://example.org/release" not in blob                   # the ref string is not copied into the prompt
    assert "ops@acme-corp.io" in out["result"]                         # caller sees the rehydrated value
    assert len(requests) == 1 and out["cost_usd"] < out["counterfactual_usd"]
    assert ledger.summary()["requests"] == 1


def test_public_file_and_search_query(env):
    _, upstream, _, d, _, _ = env
    assert run(d.delegate("extract", ["docs/notes.md"]))["lane"] == "contributor"
    assert "version 2 ships Friday" in json.dumps(upstream.calls[0][1])
    out = run(d.delegate("search", ["python asyncio timeouts", "query:rust lifetimes"]))
    assert out["lane"] == "contributor" and out["sources"] == 2
    blob = json.dumps(upstream.calls[1][1])
    assert "Result A about python asyncio timeouts" in blob and "Result B about rust lifetimes" in blob


def test_free_text_instruction_forces_standard_and_is_the_only_unmasked_difference(env):
    _, upstream, ledger, d, _, _ = env
    out = run(d.delegate("summarize", ["docs/notes.md"], instruction="Focus on the dates. Be terse."))
    assert out["lane"] == "standard" and out["model"] == "muse-spark-1.3"
    model, sent = upstream.calls[0]
    assert model == "muse-spark-1.3" and sent[-1]["content"] == "Focus on the dates. Be terse."
    assert ledger.db.execute("SELECT sent_payload, reason FROM requests").fetchone()[0] is None
    assert "by origin" in ledger.db.execute("SELECT reason FROM requests").fetchone()[0]
    # A blank instruction is not free text.
    assert run(d.delegate("summarize", ["docs/notes.md"], instruction="   "))["lane"] == "contributor"


def test_free_text_never_reaches_contributor_for_any_caller_or_content(env):
    fetcher, upstream, _, _, _, _ = env
    import random
    rng = random.Random(3)
    for caller in (Origin.ANTHROPIC, Origin.OPENAI, Origin.UNKNOWN_MODEL):
        d = Delegator(fetcher, upstream, DelegateConfig(api_base="x", api_key="x", caller=caller, billing="paid"))
        for _ in range(25):
            marker = f"FREE-{rng.randrange(10**9)}"
            task = rng.choice(sorted(TEMPLATES))
            ref = "q" if task == "search" else rng.choice(["docs/notes.md", "https://example.org/a"])
            out = run(d.delegate(task, [ref], instruction=f"please {marker}"))
            assert out["lane"] == "standard"
    contributor_calls = [m for model, m in upstream.calls if model.endswith("-contributor")]
    assert contributor_calls == []


def test_bad_requests_are_rejected_before_any_upstream_call(env):
    _, upstream, _, d, requests, tmp_path = env
    bad = [
        ("translate", ["docs/notes.md"]),                       # unknown task
        ("summarize", []),                                       # no refs
        ("summarize", ["docs/notes.md"] * 6),                    # too many
        ("summarize", ["just paste this text for me"]),          # not a url or file
        ("summarize", ["query:something"]),                      # queries are search-only
        ("summarize", ["../private.txt"]),                       # path traversal
        ("summarize", [str(tmp_path / "private.txt")]),          # absolute path outside the root
        ("summarize", [".secret/x.md"]),                         # hidden directory
        ("summarize", ["http://127.0.0.1:8080/"]),               # loopback
        ("summarize", ["http://localhost/"]),
        ("summarize", ["http://169.254.169.254/latest/meta-data"]),
        ("summarize", ["https://user:pw@example.org/"]),         # credentials in URL
        ("summarize", ["ftp://example.org/file"]),
        ("summarize", ["https://example.org/hop"]),              # redirects to a private address
        ("summarize", ["https://example.org/bin"]),              # not text
        ("summarize", ["https://example.org/missing"]),          # 404
    ]
    for task, refs in bad:
        with pytest.raises(SourceError):
            run(d.delegate(task, refs))
    assert upstream.calls == []
    assert [str(r.url) for r in requests if r.url.host != "example.org"] == []     # nothing else was contacted


def test_symlink_escape_is_refused(env):
    fetcher, _, _, d, _, tmp_path = env
    link = Path(fetcher.root) / "docs" / "link.md"
    try:
        link.symlink_to(tmp_path / "private.txt")
    except OSError:
        pytest.skip("symlinks not permitted on this machine")
    with pytest.raises(SourceError):
        run(d.delegate("summarize", ["docs/link.md"]))


def test_no_search_backend_and_no_public_root_are_clear_errors():
    f = PublicFetcher()
    with pytest.raises(SourceError, match="search backend"):
        run(f.search("x"))
    with pytest.raises(SourceError, match="public root"):
        f.file("a.md")


def test_url_checks_and_html_text():
    for url in ["http://[::1]/", "http://192.168.1.1/", "http://10.1.2.3/x", "http://0.0.0.0/"]:
        with pytest.raises(SourceError):
            check_public_url(url)
    check_public_url("https://8.8.8.8/")
    with pytest.raises(SourceError):
        check_public_url("https://intranet.example/", resolver=lambda h: ["10.0.0.9"])
    with pytest.raises(SourceError):
        check_public_url("https://mixed.example/", resolver=lambda h: ["8.8.8.8", "127.0.0.1"])
    assert html_to_text(PAGE).startswith("Release notes\nFixed bug 42.")


def test_caller_origin_must_be_a_foreign_model():
    with pytest.raises(ValueError):
        DelegateConfig(caller=Origin.META)
    with pytest.raises(ValueError):
        DelegateConfig(caller=Origin.USER)


def test_http_upstream_posts_openai_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json={"choices": []})

    up = HttpUpstream("https://mock/v1", "k", httpx.MockTransport(handler))
    assert run(up("muse-spark-1.3", [{"role": "user", "content": "hi"}])) == {"choices": []}
    assert seen["url"] == "https://mock/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["body"] == {"model": "muse-spark-1.3", "messages": [{"role": "user", "content": "hi"}]}


# ---- MCP server ----

def test_mcp_tools_are_registered_and_callable(env, tmp_path):
    _, upstream, _, d, _, _ = env
    mem = Memory()
    mem.add("project_fact", "Gateway runs on port 8787", origin=Origin.USER, label=Label.PUBLIC, project="demo", key="port")
    mem.add("project_fact", "Customer list is under NDA", origin=Origin.USER, label=Label.CONFIDENTIAL, project="demo")
    mem.add("project_fact", "token " + KEY, origin=Origin.USER, label=Label.PUBLIC, project="demo")
    home = tmp_path / "codex"
    shutil.copytree(FIXTURES, home)
    server = build_server(mem, d, quota_reader=lambda: read_codex_quota(home))

    async def go():
        tools = {t.name: t for t in await server.list_tools()}
        assert set(tools) == {"delegate", "recall", "quota"}
        assert tools["delegate"].inputSchema["required"] == ["task_type", "refs"]
        delegated = unwrap(await server.call_tool("delegate", {"task_type": "summarize", "refs": ["docs/notes.md"]}))
        recalled = unwrap(await server.call_tool("recall", {"query": "gateway port", "project": "demo"}))
        nda = unwrap(await server.call_tool("recall", {"query": "NDA", "project": "demo"}))
        secret = unwrap(await server.call_tool("recall", {"query": "token", "project": "demo"}))
        q = unwrap(await server.call_tool("quota", {}))
        forced = unwrap(await server.call_tool("delegate", {"task_type": "summarize", "refs": ["docs/notes.md"],
                                                        "instruction": "be brief"}))
        with pytest.raises(Exception, match="task_type"):
            await server.call_tool("delegate", {"task_type": "nope", "refs": ["docs/notes.md"]})
        return delegated, recalled, nda, secret, q, forced

    delegated, recalled, nda, secret, q, forced = run(go())
    assert delegated["lane"] == "contributor" and "bug 42" in delegated["result"]
    assert [r["key"] for r in recalled["result"]] == ["port"]
    assert recalled["result"][0]["origin"] == "user" and recalled["result"][0]["label"] == "public"
    assert [r["content"] for r in nda["result"]] == ["Customer list is under NDA"]
    assert secret["result"] == []                                   # credentials never come back
    assert q["available"] and q["primary"]["used_percent"] in (10.0, 42.5)
    assert forced["lane"] == "standard"
    assert not any("be brief" in json.dumps(m) for model, m in upstream.calls if model.endswith("-contributor"))
