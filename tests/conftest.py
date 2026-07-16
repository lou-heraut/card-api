"""Rend card_api, card et stase importables sans installation (dev).

En production l'image Docker installe card et stase depuis GitHub.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

for p in (
    _ROOT / "src",
    _ROOT.parent / "card" / "src",
    _ROOT.parent.parent / "EXstat_project" / "stase" / "src",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
