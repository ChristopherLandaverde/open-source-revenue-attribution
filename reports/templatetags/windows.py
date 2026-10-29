"""The lookback window in words: "90-day lookback", or no cap (attribution.describe_window)."""

from django import template

import attribution

register = template.Library()


@register.filter
def window(lookback_days):
    return attribution.describe_window(lookback_days)
