import json
import os

LOCATIONS_FILE = os.path.join(os.path.dirname(__file__), "locations.json")


def load_locations():
    """Returns {lowercased location name: PST ServeeAddress1 value to search on}."""
    if not os.path.exists(LOCATIONS_FILE):
        return {}
    with open(LOCATIONS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {name.strip().lower(): address.strip() for name, address in raw.items()}
