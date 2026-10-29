"""Pure-Python attribution logic.

No Django or other framework imports belong in this package (enforced by
tests/test_architecture.py). The web app converts its records into these
plain data types and renders whatever comes back.

Attribution here reports *association under a named model*. It does not
estimate causal impact or incrementality.
"""

from attribution.first_touch import FirstTouch
from attribution.influence import InfluenceRow, influence_by_campaign
from attribution.journey import Eligibility, Journey, JourneyStep, build_journey
from attribution.models import LastTouch, Linear, PositionBased, TimeDecay, standard_models
from attribution.types import (
    DEFAULT_LOOKBACK_DAYS,
    UNATTRIBUTED,
    AttributionModel,
    Conversion,
    Credit,
    Touchpoint,
    allocate,
    describe_window,
    eligible_touchpoints,
    summarize_by_campaign,
)

__all__ = [
    "InfluenceRow",
    "LastTouch",
    "Linear",
    "PositionBased",
    "TimeDecay",
    "allocate",
    "describe_window",
    "influence_by_campaign",
    "standard_models",
    "DEFAULT_LOOKBACK_DAYS",
    "UNATTRIBUTED",
    "AttributionModel",
    "Conversion",
    "Credit",
    "Eligibility",
    "FirstTouch",
    "Journey",
    "JourneyStep",
    "Touchpoint",
    "build_journey",
    "eligible_touchpoints",
    "summarize_by_campaign",
]
