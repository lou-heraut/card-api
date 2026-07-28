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


def test_le_service_annonce_la_version_du_paquet():
    """`versions()` lit les métadonnées de l'INSTALLATION, pas le
    pyproject. Une installation éditable faite avant un changement de
    version garde l'ancien numéro : le service annonçait ainsi `0.1.0`
    pour les trois paquets alors que les dépôts étaient en 0.5.0 et
    0.2.0, et chaque réponse, chaque bandeau de CSV et la pastille de
    `/docs` le répétaient.

    En production l'image est reconstruite, donc le cas est local. Mais
    un résultat qui se cite avec un mauvais numéro est exactement ce que
    la discipline de versions doit empêcher, et le remède tient en un
    `pip install -e .` que personne ne pense à relancer. Autant que ça
    casse ici.
    """
    from card_api.main import versions

    paquet = _version("pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    annonce = versions()["api_version"]
    assert annonce == paquet, (
        f"le service annonce {annonce}, le paquet est en {paquet} : "
        "réinstaller l'environnement (cf. INSTALL.md)"
    )
