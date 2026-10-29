"""Billing mode: whether Meta treats this account's traffic as paid (ToS §5) or non-paid (§6).

Meta Model API ToS §13.3: use paid with promotional credits (hackathon credits included) counts
as Non-Paid Services unless Meta says otherwise, and the account's billing page says content sent
while free credits are in use may be used for product improvement. Under §6 every request, on
Standard models too, may be used for training and must not carry sensitive, confidential or
personal information (§6.2). Only paid use is excluded from training (§5.1).

So on credits the Standard lane is not private: a request that fails the Contributor test must
stay on this machine, on a local model if one is configured, and is otherwise held back.
"""
from .router import HELD, LOCAL, STANDARD

PAID = "paid"
CREDITS = "credits"
MODES = (PAID, CREDITS)


def parse_billing(value: str) -> str:
    mode = (value or "").strip().lower()
    if mode not in MODES:
        raise ValueError(f"billing must be one of {list(MODES)}, got {value!r}")
    return mode


def non_contributor_lane(billing: str, has_local: bool) -> str:
    """Where a request that may not go to Contributor goes instead."""
    if billing == PAID:
        return STANDARD
    return LOCAL if has_local else HELD


def held_reason(reason: str) -> str:
    return ("held: on promotional credits every Meta request is non-paid (ToS §13.3, §6.2), "
            f"and this one is not contributable ({reason}); configure a local model or paid billing")
