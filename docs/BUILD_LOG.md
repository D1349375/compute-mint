# Build log

Everything in this repository was created during the Meta Global AI Developer Hackathon (building period Oct 27 – Nov 4, 2026). Commit timestamps are the source of truth.

| Date (UTC+8) | Work |
|---|---|
| 2026-10-26 | Pre-build analysis (scripts written after kickoff): repetition and sensitivity scan of the author's own local agent sessions. Only aggregates are published. |
| 2026-10-27 | Repository created; plan and skeleton. |
| 2026-10-27 | Gateway v0: confidentiality lattice with a non-overridable floor, taint tracking with gateway provenance, session-consistent masking vault, Contributor/Standard routing with clean-context assembly, Meta price table, counterfactual SQLite ledger, OpenAI-compatible proxy. 13 unit tests against a mock upstream, including a randomized check that no injected secret ever reaches a Contributor request. |
| 2026-10-27 | Cross-agent batch 1 (separate worktree): `Origin` dimension so output from Claude, GPT or an unidentified model can never enter a Contributor request (including Meta replies derived from it), with a randomized multi-step test; personal memory in SQLite with origin and label per entry; MCP server (`delegate` with fixed templates over sources the gateway fetches itself and Standard-only free text, `recall`, `quota`); read-only Codex `rate_limits` reader tested on hand-made fixtures; project-card generator that rewrites only the marked block of `AGENTS.md`/`CLAUDE.md`. |
