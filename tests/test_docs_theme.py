"""Le thème sombre de `/docs`.

Ce fichier existe à cause d'un échec précis : un premier thème écrit à la
main a été livré alors qu'il ne recouvrait qu'une fraction du CSS de
Swagger. Il avait été « vérifié » en constatant que le CSS était INJECTÉ,
jamais que la page RENDAIT ; à l'écran, la moitié des composants
restaient clairs sur fond sombre. D'où les garanties ci-dessous, qui sont
toutes des choses que ce thème-là aurait ratées.

Ce qu'aucun test ne remplace, et qui reste la vraie vérification : ouvrir
la page et la regarder (mode d'emploi dans `docs/dev/THEME_DOCS.md`).
"""

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import conftest  # noqa: F401  (chemins card/stase/card_api)
from card_api.main import app

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_theme  # noqa: E402

client = TestClient(app)

CSS_URL = "/static/swagger-theme.css"


@pytest.fixture(scope="module")
def css():
    r = client.get(CSS_URL)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    return r.text


def test_docs_charge_le_theme_apres_le_css_de_swagger():
    """L'ordre fait tout : les sélecteurs du thème sont ceux de Swagger,
    donc de spécificité égale, donc c'est le dernier chargé qui gagne."""
    html = client.get("/docs").text
    i_swagger = html.index("swagger-ui.css")
    i_theme = html.index("swagger-theme.css")
    assert i_swagger < i_theme
    # Les deux réglages d'usage, indépendants du thème.
    assert '"tryItOutEnabled": true' in html
    assert '"defaultModelsExpandDepth": -1' in html


def test_la_feuille_est_syntaxiquement_saine(css):
    """Une `url("data:image/svg+xml;…")` coupée sur son point-virgule
    laisse un guillemet ouvert, et le navigateur avale silencieusement
    tout ce qui suit. Aucun message, aucune erreur : la page rend juste à
    moitié. C'est exactement ce qui s'était produit."""
    build_theme.check(css)


def test_le_theme_couvre_vraiment_swagger(css):
    """Un thème à moitié appliqué est pire que pas de thème. La première
    tentative posait une centaine de règles ; il en faut un ordre de
    grandeur de plus pour recouvrir les 726 déclarations de couleur de
    Swagger."""
    assert css.count("{") > 400
    for selecteur in (
        ".swagger-ui .opblock",                    # les blocs
        ".opblock-summary-method",                 # le badge de méthode
        "pre.microlight",                          # les blocs de code
        ".swagger-ui .btn",                        # les boutons
        "input[type=text]",                        # les champs
        ".swagger-ui .opblock-tag",                # les titres de section
        ".swagger-ui table",                       # les tableaux de paramètres
        ".invalid",                                # l'état d'erreur
    ):
        assert selecteur in css, selecteur


def test_la_palette_validee_est_bien_celle_du_theme(css):
    """La gamme approuvée sur maquette. Volontairement ouverte : creux,
    fond, bloc, filet, texte. La tasser près du noir donne l'impression
    d'un filtre basse luminosité plutôt que d'un thème."""
    for token, valeur in (("--ground", "#131313"), ("--surface", "#1d1d1d"),
                          ("--well", "#0e0e0e"), ("--line", "#383838"),
                          ("--text", "#ececec")):
        assert f"{token}:{valeur}" in css, token
    # Couleurs de méthode : distinctes en vision deutéranope, et jamais
    # seules porteuses de l'information (le mot GET/POST/DELETE reste).
    for token, valeur in (("--get", "#8ab4dc"), ("--post", "#72b3a2"),
                          ("--del", "#e09b78")):
        assert f"{token}:{valeur}" in css, token


def test_pas_de_mode_sombre_natif_de_swagger(css):
    """Swagger a son propre `html.dark-mode`, qu'on n'active pas.
    Transposer ses règles n'ajouterait que du bruit, et les casserait
    pour qui l'activerait."""
    assert "dark-mode" not in css


def test_le_fichier_servi_est_bien_celui_que_produit_le_script(css):
    """Le CSS est un artefact généré : s'il est retouché à la main, la
    prochaine reconstruction efface la retouche sans prévenir."""
    assert "FICHIER GÉNÉRÉ" in css
    assert "scripts/build_theme.py" in css


def test_le_calque_ne_retourne_pas_ce_qui_est_deja_sombre():
    """Garde-fou du générateur : Swagger peint ses blocs de code en
    sombre (`#333`) avec du texte blanc. Transposés, ils repartaient en
    clair avec du texte noir, donc illisibles sur la page."""
    regle = "pre.microlight{background:#333;color:#fff}"
    assert build_theme.already_dark("background:#333;color:#fff")
    assert build_theme.transpose(f".x {regle}") == ""
    # mais une surface claire, elle, est bien transposée
    sombre = build_theme.transpose(".y{background:#fff;color:#000}")
    assert re.search(r"background:#1[0-9a-f]{5}", sombre)
