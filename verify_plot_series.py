"""Test plot series config loading."""

import os
import django
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import MessageLabel


# Load plot series config (same logic as view)
def is_valid_color(color):
    if not color or not isinstance(color, str):
        return False
    if color.startswith("#"):
        return len(color) in (4, 7, 9) and all(
            c in "0123456789abcdefABCDEF" for c in color[1:]
        )
    css_colors = {
        "red",
        "blue",
        "green",
        "yellow",
        "purple",
        "orange",
        "pink",
        "brown",
        "black",
        "white",
        "gray",
        "grey",
        "cyan",
        "magenta",
        "lime",
        "navy",
        "teal",
        "aqua",
        "maroon",
        "olive",
        "fuchsia",
        "silver",
        "gold",
    }
    return color.lower() in css_colors


plot_series_config = []
try:
    with open("json/plot_series.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    allowed_labels = set(MessageLabel.objects.values_list("label", flat=True))
    for entry in config:
        label = entry.get("label")
        display_name = entry.get("display_name")
        color = entry.get("color")
        if allowed_labels and label not in allowed_labels:
            continue
        if not is_valid_color(color):
            color = "#2563eb"
        plot_series_config.append(
            {
                "key": label,
                "label": label,
                "display_name": display_name or label,
                "color": color,
                "ml_label": label,
            }
        )
except Exception as e:
    print(f"Error loading plot series: {e}")

print(f"Loaded {len(plot_series_config)} plot series:")
for series in plot_series_config:
    print(f"  - {series['display_name']} ({series['label']}) - {series['color']}")

if any(s["label"] == "ghosted" for s in plot_series_config):
    print("\n❌ ERROR: 'ghosted' still in plot series!")
else:
    print("\n✅ SUCCESS: 'ghosted' removed from plot series")
