"""
Small template helpers for forms.

    {% load form_tags %}
    {% if field.name|one_of:"sale_date,due_date" %}

Django's `in` against a string is a substring test, so
`'customer' in 'transport_paid_by_customer'` is true - which once rendered the
customer dropdown twice on the sale form. `one_of` compares whole names.
"""

from django import template

register = template.Library()


@register.filter
def one_of(value, names):
    return str(value) in {name.strip() for name in str(names).split(",")}


@register.filter
def qty(value, places=3):
    """{{ item.bag_count|qty }} - a quantity or rate with up to 3 decimals, no trailing zeros."""
    from core.utils import qty_str

    if value is None or value == "":
        return ""
    return qty_str(value, int(places))
