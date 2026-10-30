"""Counterfactual ledger: what each request cost, what it would have cost, and what left the machine."""
import sqlite3
import time
from pathlib import Path

from .pricing import Usage, cost, counterfactual_cost
from .router import LOCAL

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
    chars_out INTEGER NOT NULL DEFAULT 0,  -- context size actually sent
    billing TEXT NOT NULL DEFAULT 'paid'   -- paid (ToS §5) or credits (non-paid, §6)
);
"""

REQUEST_COLUMNS = ("id", "ts", "session", "lane", "model", "context_label", "prompt_tokens", "cached_tokens",
                   "completion_tokens", "cost", "counterfactual", "masked_spans", "reason", "sent_payload",
                   "chars_in", "chars_out", "billing")


class Ledger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        if "billing" not in {r[1] for r in self.db.execute("PRAGMA table_info(requests)")}:
            self.db.execute("ALTER TABLE requests ADD COLUMN billing TEXT NOT NULL DEFAULT 'paid'")
            self.db.commit()

    def record(self, *, session: str, lane: str, model: str, context_label: int, usage: Usage,
               masked_spans: int, reason: str, sent_payload: str | None, billing: str,
               chars_in: int = 0, chars_out: int = 0, counterfactual_model: str | None = None) -> dict:
        # A local model costs nothing; its counterfactual is the Standard model it replaced.
        row = dict(
            ts=time.time(), session=session, lane=lane, model=model, context_label=int(context_label),
            prompt_tokens=usage.prompt_tokens, cached_tokens=usage.cached_tokens,
            completion_tokens=usage.completion_tokens, cost=0.0 if lane == LOCAL else cost(model, usage),
            counterfactual=counterfactual_cost(counterfactual_model or model, usage), masked_spans=masked_spans,
            reason=reason, sent_payload=sent_payload, chars_in=chars_in, chars_out=chars_out, billing=billing,
        )
        cols = ", ".join(row)
        self.db.execute(f"INSERT INTO requests ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        self.db.commit()
        return row

    def requests(self, session: str | None = None, lane: str | None = None, limit: int = 50, offset: int = 0,
                 payload: bool = False) -> dict:
        """One page of rows, newest first. `sent_payload` is included only when asked for."""
        conds, args = [], []
        for col, value in (("session", session), ("lane", lane)):
            if value:
                conds.append(f"{col} = ?")
                args.append(value)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        total = self.db.execute(f"SELECT COUNT(*) FROM requests {where}", args).fetchone()[0]
        cols = [c for c in REQUEST_COLUMNS if payload or c != "sent_payload"]
        cur = self.db.execute(f"SELECT {', '.join(cols)}, sent_payload IS NOT NULL FROM requests {where} "
                              "ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        rows = [{**dict(zip(cols, r[:-1])), "has_payload": bool(r[-1])} for r in cur.fetchall()]
        return {"total": total, "limit": limit, "offset": offset, "requests": rows}

    def request(self, request_id: int) -> dict | None:
        row = self.db.execute(f"SELECT {', '.join(REQUEST_COLUMNS)} FROM requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            return None
        out = dict(zip(REQUEST_COLUMNS, row))
        return {**out, "has_payload": out["sent_payload"] is not None}

    def sessions(self) -> list[dict]:
        cur = self.db.execute("""SELECT session, COUNT(*), MIN(ts), MAX(ts), COALESCE(SUM(cost),0),
                                        COALESCE(SUM(counterfactual),0)
                                 FROM requests GROUP BY session ORDER BY MAX(id) DESC""")
        return [{"session": s, "requests": n, "first_ts": a, "last_ts": b, "spent_usd": c, "counterfactual_usd": cf}
                for s, n, a, b, c, cf in cur.fetchall()]

    def summary(self, session: str | None = None) -> dict:
        where, args = ("WHERE session = ?", (session,)) if session else ("", ())
        cur = self.db.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(cost),0), COALESCE(SUM(counterfactual),0),
                       COALESCE(SUM(CASE WHEN lane='contributor' THEN prompt_tokens+completion_tokens END),0),
                       COALESCE(SUM(prompt_tokens+completion_tokens),0),
                       COALESCE(SUM(cached_tokens),0), COALESCE(SUM(prompt_tokens),0),
                       COALESCE(SUM(chars_in),0), COALESCE(SUM(chars_out),0),
                       COALESCE(SUM(lane='held'),0), COALESCE(SUM(lane='local'),0),
                       COALESCE(SUM(CASE WHEN billing='credits' THEN cost END),0)
                FROM requests {where}""", args)
        (n, spent, cf, contrib_tokens, all_tokens, cached, prompt, c_in, c_out,
         held, local, credits) = cur.fetchone()
        return {
            "requests": n,
            "spent_usd": spent,
            "counterfactual_usd": cf,
            "saved_usd": cf - spent,
            "contributable_token_share": contrib_tokens / all_tokens if all_tokens else 0.0,
            "effective_compute_multiplier": cf / spent if spent else None,
            "cache_hit_rate": cached / prompt if prompt else 0.0,
            "broker_context_ratio": c_out / c_in if c_in else 1.0,
            "held_requests": held,
            "local_requests": local,
            "credits_usd": credits,
        }
