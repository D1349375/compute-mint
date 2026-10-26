"""What-if shims: gateway behaviour the bench can switch on without editing the gateway.

`strict_tool_outputs` answers one question the canary check raises: the gateway labels a tool
output by the file path in the tool call's arguments, and by the project default when there is
none (test runs, shell commands). What would it cost, in contributable share, to treat such
outputs as unreviewed (CONFIDENTIAL) instead? The shim replaces `baseline_for` on the policy
instance of one app; the gateway source is untouched, and the arm that uses it is an extra,
labeled as a what-if.
"""
from compute_mint.labels import Label, join
from compute_mint.policy import Policy, tool_paths

# Tools whose output is a listing of names only; every other output without a file path is distrusted.
SAFE_TOOLS = frozenset({"list_files"})


def strict_tool_outputs(policy: Policy, safe_tools: frozenset[str] = SAFE_TOOLS) -> None:
    original = policy.baseline_for

    def baseline_for(messages: list[dict], default: Label, unknown_file: Label = Label.CONFIDENTIAL):
        inner = original(messages, default, unknown_file)
        names = {call.get("id"): (call.get("function") or {}).get("name")
                 for m in messages for call in m.get("tool_calls") or []}
        paths = tool_paths(messages)

        def baseline(i: int, msg: dict) -> Label:
            label = inner(i, msg)
            if msg.get("role") == "tool" and not paths.get(i) and names.get(msg.get("tool_call_id")) not in safe_tools:
                return join(label, unknown_file)
            return label
        return baseline

    policy.baseline_for = baseline_for
