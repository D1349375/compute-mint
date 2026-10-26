import json

from compute_mint.broker import Broker, BrokerConfig, compact_text

BIG = "\n".join(f"line {i}: ok" for i in range(2000)) + "\nTraceback: ValueError in parse()\n" + \
      "\n".join(f"line {i}: ok" for i in range(2000, 3000))


def turn(n: int) -> list[dict]:
    """A coding-agent history after n tool round trips, each returning a long log."""
    msgs = [{"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "Fix the failing parser test."}]
    for i in range(n):
        msgs.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "run_tests", "arguments": json.dumps({"run": i})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"run {i}\n" + BIG})
    return msgs


def test_current_turn_tool_output_is_sent_in_full():
    sent, stats = Broker().apply(turn(1))
    assert sent[-1]["content"].endswith("line 2999: ok")
    assert stats.compacted == 0


def test_aged_tool_output_is_compacted_and_keeps_salient_lines():
    sent, stats = Broker().apply(turn(2) + [{"role": "assistant", "content": "looking"}])
    assert stats.compacted == 2
    assert "Traceback: ValueError in parse()" in sent[3]["content"]
    assert len(sent[3]["content"]) < len(BIG) / 5


def _common_prefix(a: list[dict], b: list[dict]) -> int:
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    return k


def test_each_message_changes_representation_at_most_once():
    """The cached prefix of turn n+1 covers everything turn n sent except its newest tool output."""
    broker = Broker()
    prev = None
    for n in range(1, 6):
        sent, _ = broker.apply(turn(n))
        if prev is not None:
            assert _common_prefix(prev, sent) >= len(prev) - 1
        prev = sent


def simulated_cost(requests: list[list[dict]]) -> float:
    """Prefix-cache cost model in character units: cached read 0.15, uncached 1.25 (Muse Standard ratio)."""
    total, prev = 0.0, ""
    for msgs in requests:
        text = json.dumps(msgs)
        k = 0
        while k < min(len(prev), len(text)) and prev[k] == text[k]:
            k += 1
        total += k * 0.15 + (len(text) - k) * 1.25
        prev = text
    return total


def test_broker_beats_raw_and_naive_compression_under_prefix_caching():
    raw = [turn(n) for n in range(1, 9)]
    broker = Broker()
    brokered = [broker.apply(t)[0] for t in raw]

    # Naive compressor with the same fidelity policy (newest tool output kept in full), but it
    # re-summarizes older outputs every turn, so their text differs from turn to turn.
    def naive(msgs: list[dict], n: int) -> list[dict]:
        last = max(i for i, m in enumerate(msgs) if m.get("role") == "assistant")
        out = []
        for i, m in enumerate(msgs):
            m = dict(m)
            if m.get("role") == "tool" and i < last:
                m["content"] = f"[summary v{n}] " + compact_text(m["content"], BrokerConfig())
            out.append(m)
        return out
    naive_reqs = [naive(t, n) for n, t in enumerate(raw)]

    c_raw, c_broker, c_naive = simulated_cost(raw), simulated_cost(brokered), simulated_cost(naive_reqs)
    print(f"raw={c_raw:.0f} broker={c_broker:.0f} naive={c_naive:.0f}")
    assert c_broker < c_raw
    assert c_naive > c_broker
