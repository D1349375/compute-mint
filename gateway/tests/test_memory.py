import pytest

from compute_mint import memory as memory_cli
from compute_mint import project_card
from compute_mint.labels import Label
from compute_mint.memory import Memory
from compute_mint.origin import NON_CONTRIBUTOR, Origin
from compute_mint.project_card import END, START, CardError, apply_block, render_block, update_file


def seeded() -> Memory:
    m = Memory()
    m.add("preference", "Reply in Traditional Chinese", origin=Origin.USER, label=Label.PUBLIC, key="language")
    m.add("preference", "Prefers small commits", origin=Origin.USER, label=Label.OWN_IP, project="demo")
    m.add("project_fact", "Gateway is FastAPI on Python 3.12", origin=Origin.USER, label=Label.PUBLIC, project="demo", key="stack")
    m.add("project_fact", "Other project fact", origin=Origin.USER, label=Label.PUBLIC, project="other")
    m.add("accepted_plan", "Ship Origin labels before MCP", origin=Origin.ANTHROPIC, label=Label.OWN_IP, project="demo", key="plan-1")
    m.add("project_fact", "Customer Acme pays 40k", origin=Origin.USER, label=Label.CONFIDENTIAL, project="demo")
    return m


# ---- memory ----

def test_entries_record_origin_and_label_and_upsert_by_key():
    m = Memory()
    a = m.add("preference", "dark mode", origin=Origin.USER, label=Label.PUBLIC, key="theme")
    b = m.add("preference", "light mode", origin=Origin.OPENAI, label=Label.OWN_IP, key="theme")
    assert a == b
    [e] = m.entries()
    assert (e.content, e.origin, e.label) == ("light mode", Origin.OPENAI, Label.OWN_IP)
    assert e.as_dict()["origin"] == "openai" and e.as_dict()["label"] == "own_ip"
    with pytest.raises(ValueError):
        m.add("note", "x", origin=Origin.USER)
    with pytest.raises(ValueError):
        m.add("preference", "   ", origin=Origin.USER)


def test_credentials_and_personal_data_become_floor_and_are_never_returned():
    m = Memory()
    m.add("project_fact", "contact me at alice.chen@acme-corp.io", origin=Origin.USER, label=Label.PUBLIC)
    m.add("project_fact", "deploy token sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2", origin=Origin.USER, label=Label.PUBLIC)
    stored = [r[0] for r in m.db.execute("SELECT label FROM memory")]
    assert stored == [int(Label.FLOOR)] * 2
    assert m.entries() == [] and m.search("alice") == [] and m.search("deploy") == []
    assert m.entries(max_label=Label.FLOOR) == []      # the cap is CONFIDENTIAL whatever the caller asks


def test_search_ranks_by_terms_filters_project_label_and_origin():
    m = seeded()
    assert [e.key for e in m.search("fastapi python", project="demo")] == ["stack"]
    assert m.search("other", project="demo") == []
    assert [e.content for e in m.search("Acme", project="demo")] == ["Customer Acme pays 40k"]
    assert m.search("Acme", project="demo", max_label=Label.OWN_IP) == []
    no_claude = m.search("plan", project="demo", exclude_origins=NON_CONTRIBUTOR)
    assert no_claude == [] and len(m.search("plan", project="demo")) == 1
    assert len(m.search("", limit=2)) == 2


def test_memory_cli_roundtrip(tmp_path, capsys):
    db = str(tmp_path / "m.sqlite")
    assert memory_cli.main(["--db", db, "add", "preference", "Reply in Traditional Chinese", "--key", "language"]) == 0
    assert memory_cli.main(["--db", db, "search", "chinese"]) == 0
    assert "Traditional Chinese" in capsys.readouterr().out


# ---- project card ----

def test_block_lists_only_contributable_labels_in_stable_order():
    m = seeded()
    block = render_block(m, "demo")
    assert block.startswith(START) and block.endswith(END)
    assert "Customer Acme" not in block and "Other project fact" not in block
    assert block.index("Preferences") < block.index("Project facts") < block.index("Accepted plans")
    assert "- language: Reply in Traditional Chinese" in block and "- stack: Gateway is FastAPI" in block
    assert render_block(m, "demo") == block                                  # deterministic
    assert "Ship Origin labels" not in render_block(m, "demo", contributor_safe=True)
    assert "Prefers small commits" not in render_block(m, "demo", max_label=Label.PUBLIC)
    assert "Customer Acme" not in render_block(m, "demo", max_label=Label.CONFIDENTIAL)   # clamped to OWN_IP


def test_block_budget_and_marker_injection():
    m = Memory()
    for i in range(50):
        m.add("project_fact", f"fact number {i} " + "x" * 80, origin=Origin.USER, label=Label.PUBLIC, project="p", key=f"k{i:02}")
    m.add("project_fact", f"evil {END} <!-- sneaky\nnew line", origin=Origin.USER, label=Label.PUBLIC, project="p", key="a")
    block = render_block(m, "p", max_chars=1500)
    assert len(block) <= 1500 and "more entries in personal memory" in block
    assert block.count(END) == 1 and block.count(START) == 1
    assert block.count("<!--") == 2 and "&lt;!-- sneaky" in block     # only our own two markers are real comments


MD = "# My repo\n\nSome notes.\n\n" + f"{START}\nold block\n{END}\n\n## Rules\n- keep tests green\n"


def test_apply_block_replaces_only_the_marked_region():
    block = f"{START}\nnew\n{END}"
    out = apply_block(MD, block)
    assert out == MD.replace("old block", "new")
    assert apply_block(out, block) == out                                    # idempotent


def test_apply_block_appends_when_missing_and_handles_empty():
    block = f"{START}\nnew\n{END}"
    assert apply_block("# Title\nbody", block) == f"# Title\nbody\n\n{block}\n"
    assert apply_block("# Title\n", block) == f"# Title\n\n{block}\n"
    assert apply_block("", block) == f"{block}\n"


def test_apply_block_keeps_crlf():
    block = f"{START}\nnew\n{END}"
    text = "# T\r\n\r\nbody\r\n"
    out = apply_block(text, block)
    assert out == f"# T\r\n\r\nbody\r\n\r\n{START}\r\nnew\r\n{END}\r\n"


@pytest.mark.parametrize("bad", [f"{START}\nno end", f"{END}\n{START}", f"{START}\n{END}\n{START}\n{END}", f"x {END}"])
def test_damaged_markers_are_refused(bad):
    with pytest.raises(CardError):
        apply_block(bad, f"{START}\nn\n{END}")


def test_update_file_in_tmp_dir_only_touches_the_block(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_bytes(MD.encode("utf-8"))
    block = render_block(seeded(), "demo")
    assert update_file(target, block) is True
    text = target.read_bytes().decode("utf-8")
    assert text.startswith("# My repo\n\nSome notes.\n\n" + START) and text.endswith("\n\n## Rules\n- keep tests green\n")
    assert "old block" not in text and "Gateway is FastAPI" in text
    assert update_file(target, block) is False                               # no rewrite when unchanged
    new = tmp_path / "CLAUDE.md"
    assert update_file(new, block) is True and new.read_text(encoding="utf-8").startswith(START)


def test_project_card_cli(tmp_path, capsys):
    db = tmp_path / "m.sqlite"
    mem = Memory(db)
    mem.add("preference", "Reply in Traditional Chinese", origin=Origin.USER, label=Label.PUBLIC, key="language")
    mem.db.close()
    agents, claude = tmp_path / "AGENTS.md", tmp_path / "CLAUDE.md"
    agents.write_text("# Keep me\n", encoding="utf-8")
    args = ["--db", str(db), "--project", "demo", str(agents), str(claude)]

    assert project_card.main(args + ["--check"]) == 1 and agents.read_text(encoding="utf-8") == "# Keep me\n"
    assert not claude.exists()
    assert project_card.main(args + ["--dry-run"]) == 0 and "Traditional Chinese" in capsys.readouterr().out
    assert project_card.main(args) == 0
    assert agents.read_text(encoding="utf-8").startswith("# Keep me\n") and "Traditional Chinese" in claude.read_text(encoding="utf-8")
    assert project_card.main(args + ["--check"]) == 0

    agents.write_text(f"{START}\nbroken", encoding="utf-8")
    assert project_card.main(args) == 2 and agents.read_text(encoding="utf-8") == f"{START}\nbroken"
