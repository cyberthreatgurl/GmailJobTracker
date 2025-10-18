from django import template

register = template.Library()


@register.filter
def label_display(value):
    """Convert ml_label to human-readable format"""
    if not value:
        return "Unknown"
    return value.replace("_", " ").title()


@register.filter
def split(value, separator=","):
    """Split a string by separator"""
    if not value:
        return []
    return value.split(separator)


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key"""
    if not dictionary or not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)


@register.filter
def as_percentage(value):
    """Convert decimal confidence (0.0-1.0) to percentage (0-100)"""
    if value is None:
        return None
    try:
        return float(value) * 100
    except (ValueError, TypeError):
        return None
