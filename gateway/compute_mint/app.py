"""OpenAI-compatible proxy.

Agents point their base_url at this server. Per-request headers:
- x-cm-session: session id (defaults to a hash of the first message)
- x-cm-project: baseline label of this project's content: public | own_ip | confidential
- x-cm-dial:    strictest label the user agrees to contribute: public | own_ip
- x-cm-client:  model behind the calling agent: anthropic | openai | unknown (default unknown)
- x-cm-root:    absolute path of the agent's working directory (places relative paths in tool output;
                optional, the system prompt is searched for it otherwise)

Billing (CM_BILLING, default credits) decides where non-contributable requests go: Standard when
the account pays (ToS §5), otherwise a local model or nowhere (see billing.py).
"""
import os
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .billing import CREDITS, held_reason, non_contributor_lane, parse_billing
from .broker import Broker
from .context import Provenance, fingerprint
from .labels import Label
from .ledger import Ledger
from .policy import Policy, clean_root
from .origin import OriginTracker, parse_client
from .pricing import Usage
from .router import CONTRIBUTOR, HELD, LOCAL, STANDARD, payload_digest, rehydrate_response, route
from .vault import Vault

LABEL_NAMES = {"public": Label.PUBLIC, "own_ip": Label.OWN_IP, "confidential": Label.CONFIDENTIAL}


@dataclass
class Config:
    api_base: str = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
    api_key: str = os.environ.get("META_API_KEY", "")
    contributor_model: str = os.environ.get("CONTRIBUTOR_MODEL", "muse-spark-1.3-contributor")
    standard_model: str = os.environ.get("STANDARD_MODEL", "muse-spark-1.3")
    ledger_path: str = os.environ.get("LEDGER_PATH", ":memory:")
    policy_path: str = os.environ.get("POLICY_PATH", ":memory:")
    billing: str = os.environ.get("CM_BILLING", CREDITS)          # paid | credits; unknown means credits
    local_api_base: str = os.environ.get("LOCAL_API_BASE", "")    # OpenAI-compatible server on this machine
    local_model: str = os.environ.get("LOCAL_MODEL", "muse-glimmer")
    output_paths: bool = True    # label tool output by the paths it names
    fingerprints: bool = True    # label tool output by sensitive text read earlier
    fingerprint_threshold: int = 2   # score a message needs (see fingerprint.py)


@dataclass
class SessionState:
    vault: Vault = field(default_factory=Vault)
    provenance: Provenance = field(default_factory=Provenance)
    broker: Broker = field(default_factory=Broker)
    origin: OriginTracker = field(default_factory=OriginTracker)


def create_app(config: Config | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    config = config or Config()
    billing = parse_billing(config.billing)
    app = FastAPI(title="Compute Mint gateway")
    ledger = Ledger(config.ledger_path)
    policy = Policy(config.policy_path, output_paths=config.output_paths, fingerprints=config.fingerprints,
                    fingerprint_threshold=config.fingerprint_threshold)
    sessions: dict[str, SessionState] = {}
    client = httpx.AsyncClient(base_url=config.api_base, transport=transport, timeout=300,
                               headers={"Authorization": f"Bearer {config.api_key}"})
    local = (httpx.AsyncClient(base_url=config.local_api_base, transport=transport, timeout=300)
             if config.local_api_base else None)
    app.state.ledger = ledger
    app.state.policy = policy
    app.state.sessions = sessions

    def header_label(request: Request, name: str, default: str) -> Label:
        value = request.headers.get(name, default).lower()
        if value not in LABEL_NAMES:
            raise HTTPException(400, f"{name} must be one of {sorted(LABEL_NAMES)}")
        return LABEL_NAMES[value]

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        body = await request.json()
        if body.get("stream"):
            raise HTTPException(400, "streaming is not supported yet")
        messages = body.get("messages") or []
        if not messages:
            raise HTTPException(400, "messages is required")
        session_id = request.headers.get("x-cm-session") or fingerprint(messages[0])[:16]
        baseline = header_label(request, "x-cm-project", "own_ip")
        dial = header_label(request, "x-cm-dial", "public")
        try:
            caller = parse_client(request.headers.get("x-cm-client"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        root = clean_root(request.headers.get("x-cm-root"))
        state = sessions.setdefault(session_id, SessionState())

        origins = state.origin.of_messages(messages, state.provenance, caller)
        decision = route(messages, baseline=baseline, dial=dial, vault=state.vault, provenance=state.provenance,
                         baseline_for=policy.baseline_for(messages, baseline, root=root), origins=origins)
        if decision.blocked_by:
            policy.enqueue_unknown(messages, decision.blocked_by, root=root)
        lane = decision.lane if decision.lane == CONTRIBUTOR else non_contributor_lane(billing, local is not None)
        if lane == HELD:
            reason = held_reason(decision.reason)
            ledger.record(session=session_id, lane=HELD, model=config.standard_model,
                          context_label=decision.context_label, usage=Usage(0, 0, 0), masked_spans=0,
                          reason=reason, sent_payload=None, billing=billing)
            return JSONResponse({"error": {"type": "compute_mint_held", "code": "not_contributable_on_credits",
                                           "message": reason}},
                                status_code=403, headers={"x-cm-lane": HELD, "x-cm-billing": billing})
        model = {CONTRIBUTOR: config.contributor_model, STANDARD: config.standard_model,
                 LOCAL: config.local_model}[lane]
        sent, bstats = state.broker.apply(decision.messages)
        upstream_body = {**body, "model": model, "messages": sent}

        resp = await (local if lane == LOCAL else client).post("/chat/completions", json=upstream_body)
        if resp.status_code >= 400:
            return JSONResponse(resp.json() if resp.content else {}, status_code=resp.status_code)
        data = resp.json()
        if lane == CONTRIBUTOR:
            data = rehydrate_response(data, state.vault)

        for choice in data.get("choices", []):
            if choice.get("message"):
                state.provenance.record(choice["message"], decision.context_label)
                state.origin.record_reply(choice["message"], origins)

        row = ledger.record(
            session=session_id, lane=lane, model=model, context_label=decision.context_label,
            usage=Usage.from_openai(data.get("usage")), masked_spans=decision.masked_spans,
            reason=decision.reason,
            sent_payload=payload_digest(sent) if lane == CONTRIBUTOR else None,
            chars_in=bstats.chars_in, chars_out=bstats.chars_out, billing=billing,
            counterfactual_model=config.standard_model if lane == LOCAL else None,
        )
        headers = {
            "x-cm-lane": lane,
            "x-cm-billing": billing,
            "x-cm-cost": f"{row['cost']:.6f}",
            "x-cm-counterfactual": f"{row['counterfactual']:.6f}",
            "x-cm-masked-spans": str(decision.masked_spans),
            "x-cm-broker-chars": f"{bstats.chars_in}->{bstats.chars_out}",
        }
        return JSONResponse(data, headers=headers)

    @app.get("/v1/ledger/summary")
    async def summary(session: str | None = None) -> dict:
        return ledger.summary(session)

    # Read-only views for the dashboard. They show what the ledger already holds; nothing here routes.
    @app.get("/v1/ledger/requests")
    async def ledger_requests(session: str | None = None, lane: str | None = None, limit: int = 50,
                              offset: int = 0, payload: bool = False) -> dict:
        if lane is not None and lane not in (CONTRIBUTOR, STANDARD, LOCAL, HELD):
            raise HTTPException(400, f"lane must be one of {[CONTRIBUTOR, STANDARD, LOCAL, HELD]}")
        if not 1 <= limit <= 500 or offset < 0:
            raise HTTPException(400, "limit must be 1..500 and offset >= 0")
        page = ledger.requests(session, lane, limit, offset, payload)
        for row in page["requests"]:
            row["context_label"] = Label(row["context_label"]).name
        return page

    @app.get("/v1/ledger/requests/{request_id}")
    async def ledger_request(request_id: int) -> dict:
        row = ledger.request(request_id)
        if row is None:
            raise HTTPException(404, "no such request")
        row["context_label"] = Label(row["context_label"]).name
        return row

    @app.get("/v1/ledger/sessions")
    async def ledger_sessions() -> dict:
        return {"sessions": ledger.sessions()}

    @app.get("/v1/status")
    async def status() -> dict:
        return {"billing": billing, "local_model": config.local_model if local is not None else None,
                "contributor_model": config.contributor_model, "standard_model": config.standard_model}

    @app.get("/v1/review")
    async def review_queue() -> dict:
        return {"pending": policy.pending(), "rules": [{"pattern": p, "label": l.name} for p, l in policy.rules()]}

    @app.post("/v1/review/{item_id}")
    async def review_decide(item_id: int, request: Request) -> dict:
        body = await request.json()
        label = LABEL_NAMES.get(str(body.get("label", "")).lower())
        if label is None:
            raise HTTPException(400, f"label must be one of {sorted(LABEL_NAMES)}")
        try:
            pattern = policy.decide(item_id, label, body.get("pattern"))
        except KeyError:
            raise HTTPException(404, "no such review item")
        return {"pattern": pattern, "label": label.name}

    return app


app = create_app()
