"""The band constructor and its two direction constants.

Lives on its own so every bands/<vertical>.py can import it without
importing the registry that imports them -- the circular-import trap
this package would otherwise walk straight into.
"""
from typing import Any, Dict, Optional

HIGHER = "higher_better"
LOWER = "lower_better"


def band(label, average=None, target=None, floor=None, unit="%",
          direction=HIGHER, scale_max=None, reading="", source=""):
    return {
        "label": label, "average": average, "target": target, "floor": floor,
        "unit": unit, "direction": direction, "scale_max": scale_max,
        "reading": reading, "source": source,
    }


