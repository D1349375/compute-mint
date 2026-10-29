"""MCP server (stdio) that lets any MCP-capable agent use Compute Mint without a token.

    python -m compute_mint.mcp_server

Tools:
- delegate(task_type, refs, instruction=None): run a fixed template over public sources we fetch
- recall(query, project=None, limit=5): search personal memory
- quota(): Codex rate limits, read from local session logs

Register with Claude Code:  claude mcp add compute-mint -- <python> -m compute_mint.mcp_server
Register with Codex (config.toml):  [mcp_servers.compute-mint] command = "<python>" args = ["-m", "compute_mint.mcp_server"]
"""
from typing import Callable

from mcp.server.fastmcp import FastMCP

from .delegate import Delegator, DelegateConfig, HttpUpstream, TEMPLATES
from .labels import Label
from .ledger import Ledger
from .memory import Memory, default_path
from .quota import read_codex_quota
from .sources import PublicFetcher, SourceError


def build_server(memory: Memory, delegator: Delegator, quota_reader: Callable[[], dict] = read_codex_quota) -> FastMCP:
    server = FastMCP("compute-mint")

    @server.tool()
    async def delegate(task_type: str, refs: list[str], instruction: str | None = None) -> dict:
        """Offload a bounded task to a cheaper model.

        task_type: one of summarize, extract, explain_error, search.
        refs: 1-5 references. Each is a public http(s) URL, a file path under the configured public
        root, or (search only) a query string. We fetch the text ourselves, so private files and
        pasted text are not accepted. instruction: optional extra free text; because you wrote it,
        it makes the request ineligible for the cheapest tier.
        """
        try:
            return await delegator.delegate(task_type, refs, instruction)
        except SourceError as e:
            raise ValueError(f"{e} (task types: {', '.join(sorted(TEMPLATES))})") from None

    @server.tool()
    def recall(query: str, project: str | None = None, limit: int = 5) -> list[dict]:
        """Search the user's personal memory (preferences, project facts, accepted plans)."""
        found = memory.search(query, limit=max(1, min(limit, 20)), project=project, max_label=Label.CONFIDENTIAL)
        return [{k: v for k, v in e.as_dict().items() if k in ("id", "kind", "project", "key", "content", "origin", "label")}
                for e in found]

    @server.tool()
    def quota() -> dict:
        """Remaining Codex rate limit (primary and secondary windows), from local session logs."""
        return quota_reader()

    return server


def main() -> None:
    config = DelegateConfig()
    local = HttpUpstream(config.local_api_base, "") if config.local_api_base else None
    delegator = Delegator(PublicFetcher(config.public_root), HttpUpstream(config.api_base, config.api_key),
                          config, Ledger(config.ledger_path), local=local)
    build_server(Memory(default_path()), delegator).run()


if __name__ == "__main__":
    main()
