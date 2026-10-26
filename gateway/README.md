# gateway

OpenAI-compatible proxy that routes each request to Muse Spark Contributor or Standard.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn compute_mint.app:app --port 8787
```

Point an agent at `http://localhost:8787/v1`. Per-request headers:

| Header | Values | Meaning |
|---|---|---|
| `x-cm-session` | any id | groups requests for masking and provenance |
| `x-cm-project` | `public`, `own_ip`, `confidential` | baseline label of this project's content |
| `x-cm-dial` | `public`, `own_ip` | strictest label the user agrees to contribute |

`GET /v1/ledger/summary` returns spend, counterfactual spend, savings and the contributable token share.

| Module | Role |
|---|---|
| `labels.py` | PUBLIC < OWN_IP < CONFIDENTIAL < FLOOR; the dial can never reach CONFIDENTIAL or FLOOR |
| `detect.py` | deterministic credential / personal-data detectors |
| `vault.py` | session-consistent placeholders and rehydration |
| `context.py` | taint tracking; provenance of gateway-generated replies |
| `router.py` | lane decision and clean-context assembly |
| `pricing.py`, `ledger.py` | official prices and the counterfactual ledger |
| `app.py` | the proxy |
