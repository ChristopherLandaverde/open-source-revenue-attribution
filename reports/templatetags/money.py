"""Display amounts at their currency's minor unit (PRD section 6): 1200000 JPY, 18500.50 EUR."""

from decimal import Decimal

from django import template

from contracts import CURRENCY_MINOR_UNITS

register = template.Library()


@register.filter
def minor_unit(amount, currency):
    places = CURRENCY_MINOR_UNITS.get(currency, 2)
    return Decimal(amount).quantize(Decimal(1).scaleb(-places))
