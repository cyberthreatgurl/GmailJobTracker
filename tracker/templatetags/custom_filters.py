from django import template

register = template.Library()


@register.filter
def label_display(value):
    """Convert ml_label to human-readable format"""
    if not value:
        return "Unknown"
    return value.replace("_", " ").title()
