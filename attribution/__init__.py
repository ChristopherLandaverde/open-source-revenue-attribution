"""Pure-Python attribution logic.

No Django or other framework imports belong in this package (enforced by
tests/test_architecture.py). The web app converts its records into these
plain data types and renders whatever comes back.

Attribution here reports *association under a named model*. It does not
estimate causal impact or incrementality.
"""

from attribution.first_touch import FirstTouch
from attribution.types import (
    DEFAULT_LOOKBACK_DAYS,
    UNATTRIBUTED,
    AttributionModel,
    Conversion,
    Credit,
    Touchpoint,
    eligible_touchpoints,
    summarize_by_campaign,
)

__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "UNATTRIBUTED",
    "AttributionModel",
    "Conversion",
    "Credit",
    "FirstTouch",
    "Touchpoint",
    "eligible_touchpoints",
    "summarize_by_campaign",
]
