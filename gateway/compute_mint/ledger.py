"""Counterfactual ledger: what each request cost, what it would have cost, and what left the machine."""
import sqlite3
import time
from pathlib import Path

from .pricing import Usage, cost, counterfactual_cost

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session TEXT NOT NULL,
    lane TEXT NOT NULL,
    model TEXT NOT NULL,
    context_label INTEGER NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    cached_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cost REAL NOT NULL,
    counterfactual REAL NOT NULL,
    masked_spans INTEGER NOT NULL,
    reason TEXT NOT NULL,
    sent_payload TEXT,           -- what left the machine; only stored for Contributor requests
    chars_in INTEGER NOT NULL DEFAULT 0,   -- context size before the Context Broker
    chars_out INTEGER NOT NULL DEFAULT 0   -- context size actually sent
);
"""


class Ledger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    def record(self, *, session: str, lane: str, model: str, context_label: int, usage: Usage,
               masked_spans: int, reason: str, sent_payload: str | None,
               chars_in: int = 0, chars_out: int = 0) -> dict:
        row = dict(
            ts=time.time(), session=session, lane=lane, model=model, context_label=int(context_label),
            prompt_tokens=usage.prompt_tokens, cached_tokens=usage.cached_tokens,
            completion_tokens=usage.completion_tokens, cost=cost(model, usage),
            counterfactual=counterfactual_cost(model, usage), masked_spans=masked_spans,
            reason=reason, sent_payload=sent_payload, chars_in=chars_in, chars_out=chars_out,
        )
        cols = ", ".join(row)
        self.db.execute(f"INSERT INTO requests ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        self.db.commit()
        return row

    def summary(self, session: str | None = None) -> dict:
        where, args = ("WHERE session = ?", (session,)) if session else ("", ())
        cur = self.db.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(cost),0), COALESCE(SUM(counterfactual),0),
                       COALESCE(SUM(CASE WHEN lane='contributor' THEN prompt_tokens+completion_tokens END),0),
                       COALESCE(SUM(prompt_tokens+completion_tokens),0),
                       COALESCE(SUM(cached_tokens),0), COALESCE(SUM(prompt_tokens),0),
                       COALESCE(SUM(chars_in),0), COALESCE(SUM(chars_out),0)
                FROM requests {where}""", args)
        n, spent, cf, contrib_tokens, all_tokens, cached, prompt, c_in, c_out = cur.fetchone()
        return {
            "requests": n,
            "spent_usd": spent,
            "counterfactual_usd": cf,
            "saved_usd": cf - spent,
            "contributable_token_share": contrib_tokens / all_tokens if all_tokens else 0.0,
            "effective_compute_multiplier": cf / spent if spent else None,
            "cache_hit_rate": cached / prompt if prompt else 0.0,
            "broker_context_ratio": c_out / c_in if c_in else 1.0,
        }
