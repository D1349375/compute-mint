"""OpenAI-compatible proxy: /v1/chat/completions and /v1/responses, streaming or not.

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
import json
import os
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .billing import CREDITS, held_reason, non_contributor_lane, parse_billing
from .broker import Broker, BrokerStats
from .context import Provenance, fingerprint
from .labels import Label
from .ledger import Ledger
from .policy import Policy, clean_root
from .origin import Origin, OriginTracker, parse_client
from .pricing import Usage
from .responses import BadRequest, ResponsesRenderer, complete_response, stateful_field, to_chat
from .router import CONTRIBUTOR, HELD, LOCAL, STANDARD, Decision, mask_fields, payload_digest, rehydrate_response, route
from .streaming import ChatRenderer, Relay
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


@dataclass
class Admitted:
    """A request after labels, routing, billing and the Broker: where it goes and what is sent."""
    session_id: str
    state: SessionState
    lane: str
    model: str
    decision: Decision
    origins: list[Origin]
    sent: list[dict]
    bstats: BrokerStats


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

    def admit(request: Request, messages: list[dict], unlabeled: str | None = None) -> Admitted | JSONResponse:
        """Labels, routing, billing and the Broker: what a request becomes, whichever endpoint it came in on."""
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
                         baseline_for=policy.baseline_for(messages, baseline, root=root), origins=origins,
                         unlabeled=unlabeled)
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
        return Admitted(session_id, state, lane, model, decision, origins, sent, bstats)

    def upstream_body(adm: Admitted, fields: dict) -> dict:
        """What goes upstream. On Contributor, the fields next to the messages are masked like the messages."""
        extra = {k: v for k, v in fields.items() if k not in ("model", "messages")}
        if adm.lane == CONTRIBUTOR:
            extra, n = mask_fields(extra, adm.state.vault)
            adm.decision.masked_spans += n
        out = {**fields, **extra, "model": adm.model, "messages": adm.sent}
        if "store" in out:
            out["store"] = False
        return out

    def settle(adm: Admitted, usage: Usage, replies: list[dict], note: str = "") -> dict:
        """Provenance of the replies the client now holds, and the ledger row."""
        for message in replies:
            adm.state.provenance.record(message, adm.decision.context_label)
            adm.state.origin.record_reply(message, adm.origins)
        return ledger.record(
            session=adm.session_id, lane=adm.lane, model=adm.model, context_label=adm.decision.context_label,
            usage=usage, masked_spans=adm.decision.masked_spans,
            reason=f"{adm.decision.reason}; {note}" if note else adm.decision.reason,
            sent_payload=payload_digest(adm.sent) if adm.lane == CONTRIBUTOR else None,
            chars_in=adm.bstats.chars_in, chars_out=adm.bstats.chars_out, billing=billing,
            counterfactual_model=config.standard_model if adm.lane == LOCAL else None,
        )

    def route_headers(adm: Admitted) -> dict[str, str]:
        return {
            "x-cm-lane": adm.lane,
            "x-cm-billing": billing,
            "x-cm-masked-spans": str(adm.decision.masked_spans),
            "x-cm-broker-chars": f"{adm.bstats.chars_in}->{adm.bstats.chars_out}",
        }

    def cost_headers(row: dict) -> dict[str, str]:
        return {"x-cm-cost": f"{row['cost']:.6f}", "x-cm-counterfactual": f"{row['counterfactual']:.6f}"}

    async def complete(adm: Admitted, body: dict) -> dict | JSONResponse:
        """One whole upstream completion, with placeholders restored."""
        resp = await (local if adm.lane == LOCAL else client).post("/chat/completions", json=body)
        if resp.status_code >= 400:
            return JSONResponse(resp.json() if resp.content else {}, status_code=resp.status_code)
        data = resp.json()
        return rehydrate_response(data, adm.state.vault) if adm.lane == CONTRIBUTOR else data

    async def relay(adm: Admitted, body: dict, renderer) -> Response:
        """Open the upstream stream. Everything that can fail before the first byte is still a plain HTTP answer."""
        upstream = local if adm.lane == LOCAL else client
        options = {**(body.get("stream_options") or {}), "include_usage": True}
        request = upstream.build_request("POST", "/chat/completions",
                                         json={**body, "stream": True, "stream_options": options})
        headers = route_headers(adm)
        try:
            resp = await upstream.send(request, stream=True)
        except httpx.HTTPError as e:
            settle(adm, Usage(0, 0, 0), [], f"upstream unreachable ({type(e).__name__})")
            return JSONResponse({"error": {"type": "upstream_unreachable", "code": "upstream_unreachable",
                                           "message": f"upstream connection failed ({type(e).__name__})"}},
                                status_code=502, headers=headers)
        if resp.status_code >= 400:
            raw = await resp.aread()
            await resp.aclose()
            settle(adm, Usage(0, 0, 0), [], f"upstream answered {resp.status_code}")
            try:
                error = json.loads(raw) if raw else {}
            except ValueError:
                error = {"error": {"type": "upstream_error", "message": raw.decode("utf-8", "replace")}}
            return JSONResponse(error, status_code=resp.status_code, headers=headers)
        return Relay(resp, renderer, adm.state.vault if adm.lane == CONTRIBUTOR else None,
                     lambda usage, replies, note: settle(adm, usage, replies, note), headers)

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        body = await request.json()
        refusal = stateful_field(body)
        if refusal:
            return JSONResponse(refusal.body(), status_code=400)
        messages = body.get("messages") or []
        if not messages:
            raise HTTPException(400, "messages is required")
        adm = admit(request, messages)
        if isinstance(adm, JSONResponse):
            return adm
        out = upstream_body(adm, body)
        if body.get("stream"):
            include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
            return await relay(adm, out, ChatRenderer(include_usage))

        data = await complete(adm, out)
        if isinstance(data, JSONResponse):
            return data
        replies = [choice["message"] for choice in data.get("choices", []) if choice.get("message")]
        row = settle(adm, Usage.from_openai(data.get("usage")), replies)
        return JSONResponse(data, headers={**route_headers(adm), **cost_headers(row)})

    @app.post("/v1/responses")
    async def responses(request: Request) -> Response:
        body = await request.json()
        try:
            converted = to_chat(body)
        except BadRequest as e:
            return JSONResponse(e.body(), status_code=400)
        adm = admit(request, converted.messages, converted.unlabeled)
        if isinstance(adm, JSONResponse):
            return adm
        out = upstream_body(adm, converted.fields)
        if body.get("stream"):
            return await relay(adm, out, ResponsesRenderer(adm.model, body, converted.kinds))

        data = await complete(adm, out)
        if isinstance(data, JSONResponse):
            return data
        response, replies = complete_response(data, adm.model, body, converted.kinds)
        row = settle(adm, Usage.from_openai(data.get("usage")), replies)
        return JSONResponse(response, headers={**route_headers(adm), **cost_headers(row)})

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
