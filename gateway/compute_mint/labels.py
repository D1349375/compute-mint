"""Confidentiality lattice.

PUBLIC < OWN_IP < CONFIDENTIAL < FLOOR

- PUBLIC: already public or safe to publish.
- OWN_IP: the user's own content; contributable only if the user's dial allows it.
- CONFIDENTIAL: third-party or business-confidential content; never contributable as-is.
- FLOOR: personal information (including the user's own), credentials, regulated data.
  Meta Model API ToS §6.2 forbids sending these to Contributor services, so no
  user setting can lower this.
"""
from enum import IntEnum


class Label(IntEnum):
    PUBLIC = 0
    OWN_IP = 1
    CONFIDENTIAL = 2
    FLOOR = 3


def join(*labels: Label) -> Label:
    """Least upper bound: data derived from several inputs carries the strictest label."""
    return max(labels, default=Label.PUBLIC)


def contributable(label: Label, dial: Label) -> bool:
    """Whether content with `label` may go to Contributor under the user's `dial`.

    The dial is the strictest label the user is willing to contribute. It is clamped to
    OWN_IP: CONFIDENTIAL and FLOOR are never contributable regardless of the dial.
    """
    return label <= min(dial, Label.OWN_IP)
