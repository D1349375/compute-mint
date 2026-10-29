# Compute Mint

**Turn agent usage into compute — compliantly.**

Meta's Muse Spark *Contributor* tier serves the same model at a steep discount (input $0.10 vs $1.25, cached input $0.002 vs $0.15, output $0.20 vs $4.25 per 1M tokens) in exchange for permission to train on the traffic. The Model API Terms forbid sending sensitive, confidential or personal information to Contributor services, and any earlier content that is carried into a Contributor request becomes Contributor content.

Real agent sessions leak secrets and personal data into their context early and carry that context forward. In our own analysis of 683 local Claude Code and Codex sessions, only **8.8%** of agent tokens could have been sent to Contributor under a naive "switch the model mid-session" approach. That is true even though, for this token mix (≈98% cached reads), the discount works out to about **42×**.

Compute Mint is a gateway between agents and models. It:

- **tracks taint** across the context of a multi-step agent (information-flow labels);
- **partitions work into lanes**: public work goes to Contributor in a freshly assembled clean context, confidential work goes to Standard or self-hosted Muse Glimmer;
- **masks and pseudonymizes** (including code-aware renaming that keeps code runnable) so more steps can be contributed;
- **keeps a counterfactual ledger**: what you would have paid, what you paid, and exactly what left your machine;
- **learns from your approvals**, so the share of contributable work grows the more you use it.

> Status: built during the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). See [docs/BUILD_LOG.md](docs/BUILD_LOG.md) for what was created during the event.

## Layout

| Path | What |
|---|---|
| `gateway/` | OpenAI-compatible proxy: taint tracking, lanes, transforms, routing, ledger |
| `dashboard/` | Savings/exposure dashboard and the privacy–savings dial |
| `bench/` | Acceptance task set and evaluation harness |
| `docs/` | Plan, architecture, build log |

## Compliance floor

Regardless of any user setting, Compute Mint never routes personal information (including the user's own), credentials, third-party confidential data or regulated data to Contributor services. Users may only choose how much of **their own, publishable** content to contribute.

Standard is private only when the account pays. Use paid with promotional credits (hackathon credits included) counts as non-paid under the Terms (§13.3), and every non-paid request may be used for training (§6), on Standard models too. So by default (`CM_BILLING=credits`) whatever may not go to Contributor stays on this machine: it runs on a local model if one is configured and is held back otherwise. All live runs during the hackathon use credits and invented data only.

## License

TBD
