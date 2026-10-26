"""OpenAI-compatible proxy.

Agents point their base_url at this server. Per-request headers:
- x-cm-session: session id (defaults to a hash of the first message)
- x-cm-project: baseline label of this project's content: public | own_ip | confidential
- x-cm-dial:    strictest label the user agrees to contribute: public | own_ip
- x-cm-client:  model behind the calling agent: anthropic | openai | unknown (default unknown)
"""
import os
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .broker import Broker
from .context import Provenance, fingerprint
from .labels import Label
from .ledger import Ledger
from .origin import OriginTracker, parse_client
from .pricing import Usage
from .router import CONTRIBUTOR, payload_digest, rehydrate_response, route
from .vault import Vault

LABEL_NAMES = {"public": Label.PUBLIC, "own_ip": Label.OWN_IP, "confidential": Label.CONFIDENTIAL}


@dataclass
class Config:
    api_base: str = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
    api_key: str = os.environ.get("META_API_KEY", "")
    contributor_model: str = os.environ.get("CONTRIBUTOR_MODEL", "muse-spark-1.3-contributor")
    standard_model: str = os.environ.get("STANDARD_MODEL", "muse-spark-1.3")
    ledger_path: str = os.environ.get("LEDGER_PATH", ":memory:")


@dataclass
class SessionState:
    vault: Vault = field(default_factory=Vault)
    provenance: Provenance = field(default_factory=Provenance)
    broker: Broker = field(default_factory=Broker)
    origin: OriginTracker = field(default_factory=OriginTracker)


def create_app(config: Config | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    config = config or Config()
    app = FastAPI(title="Compute Mint gateway")
    ledger = Ledger(config.ledger_path)
    sessions: dict[str, SessionState] = {}
    client = httpx.AsyncClient(base_url=config.api_base, transport=transport, timeout=300,
                               headers={"Authorization": f"Bearer {config.api_key}"})
    app.state.ledger = ledger
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
        state = sessions.setdefault(session_id, SessionState())

        origins = state.origin.of_messages(messages, state.provenance, caller)
        decision = route(messages, baseline=baseline, dial=dial, vault=state.vault, provenance=state.provenance,
                         origins=origins)
        model = config.contributor_model if decision.lane == CONTRIBUTOR else config.standard_model
        sent, bstats = state.broker.apply(decision.messages)
        upstream_body = {**body, "model": model, "messages": sent}

        resp = await client.post("/chat/completions", json=upstream_body)
        if resp.status_code >= 400:
            return JSONResponse(resp.json() if resp.content else {}, status_code=resp.status_code)
        data = resp.json()
        if decision.lane == CONTRIBUTOR:
            data = rehydrate_response(data, state.vault)

        for choice in data.get("choices", []):
            if choice.get("message"):
                state.provenance.record(choice["message"], decision.context_label)
                state.origin.record_reply(choice["message"], origins)

        row = ledger.record(
            session=session_id, lane=decision.lane, model=model, context_label=decision.context_label,
            usage=Usage.from_openai(data.get("usage")), masked_spans=decision.masked_spans,
            reason=decision.reason,
            sent_payload=payload_digest(sent) if decision.lane == CONTRIBUTOR else None,
            chars_in=bstats.chars_in, chars_out=bstats.chars_out,
        )
        headers = {
            "x-cm-lane": decision.lane,
            "x-cm-cost": f"{row['cost']:.6f}",
            "x-cm-counterfactual": f"{row['counterfactual']:.6f}",
            "x-cm-masked-spans": str(decision.masked_spans),
            "x-cm-broker-chars": f"{bstats.chars_in}->{bstats.chars_out}",
        }
        return JSONResponse(data, headers=headers)

    @app.get("/v1/ledger/summary")
    async def summary(session: str | None = None) -> dict:
        return ledger.summary(session)

    return app


app = create_app()
