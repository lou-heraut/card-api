"""Les métadonnées de citation doivent annoncer la même version que le
paquet.

Un CITATION.cff qui traîne une version périmée fait citer un état qui
n'est pas celui qu'on a publié. C'est le seul endroit où un numéro doit
être recopié, donc le seul qui puisse se désaccorder : autant que ça
casse ici plutôt que dans une bibliographie.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _version(fichier, motif):
    m = re.search(motif, (ROOT / fichier).read_text(encoding="utf-8"), re.M)
    assert m, f"version introuvable dans {fichier}"
    return m.group(1)


def test_versions_de_citation_accordees():
    paquet = _version("pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    citation = _version("CITATION.cff", r'^version:\s*"([^"]+)"')
    codemeta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))

    assert citation == paquet, (
        f"CITATION.cff annonce {citation}, le paquet est en {paquet}"
    )
    assert codemeta["version"] == paquet, (
        f"codemeta.json annonce {codemeta['version']}, le paquet est en {paquet}"
    )
