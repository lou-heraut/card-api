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


import pytest


@pytest.fixture(autouse=True)
def _test_env(monkeypatch, tmp_path):
    """Quotas neutralisés (tous les tests partagent l'« IP » testclient)
    et données/journal dans un dossier temporaire."""
    from card_api import usage
    usage._hits.clear()
    monkeypatch.setattr(usage, "RATE_COMPUTE", 10_000)
    monkeypatch.setattr(usage, "RATE_LIGHT", 10_000)
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
