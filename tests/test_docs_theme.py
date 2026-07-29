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

# Deux calques, servis dans cet ordre : les couleurs sont ENGENDREES et
# ne bougent qu'a une montee de Swagger, l'identite est ECRITE A LA MAIN
# et se retouche sans rien reconstruire. Les separer est ce qui rend la
# seconde modifiable d'un simple rechargement de page.
COLORS_URL = "/static/swagger-colors.css"
IDENTITY_URL = "/static/theme-identity.css"


def _fetch(url):
    r = client.get(url)
    assert r.status_code == 200, url
    assert r.headers["content-type"].startswith("text/css")
    return r.text


@pytest.fixture(scope="module")
def colors():
    return _fetch(COLORS_URL)


@pytest.fixture(scope="module")
def identity():
    return _fetch(IDENTITY_URL)


@pytest.fixture(scope="module")
def css(colors, identity):
    """Les deux calques, dans l'ordre ou le navigateur les recoit."""
    return colors + "\n" + identity


def test_une_feuille_inconnue_est_refusee():
    """La route prend un nom en parametre : elle ne doit servir que les
    deux calques connus, pas un chemin arbitraire."""
    assert client.get("/static/autre.css").status_code == 404


def test_docs_charge_le_theme_apres_le_css_de_swagger():
    """L'ordre fait tout : les sélecteurs du thème sont ceux de Swagger,
    donc de spécificité égale, donc c'est le dernier chargé qui gagne."""
    html = client.get("/docs").text
    i_swagger = html.index("swagger-ui.css")
    i_colors = html.index("swagger-colors.css")
    i_identity = html.index("theme-identity.css")
    # Swagger, puis les couleurs, puis l'identite qui tranche.
    assert i_swagger < i_colors < i_identity
    # Chaque feuille porte l'empreinte de son contenu : sans elle, une
    # retouche reste invisible jusqu'a expiration du cache du navigateur.
    assert "swagger-colors.css?v=" in html
    assert "theme-identity.css?v=" in html
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


def test_pas_de_mode_sombre_natif_de_swagger(colors):
    """Swagger a son propre `html.dark-mode`, qu'on n'active pas.
    Transposer ses règles n'ajouterait que du bruit, et les casserait
    pour qui l'activerait."""
    assert "dark-mode" not in colors


def test_seul_le_calque_de_couleurs_est_un_artefact(colors, identity):
    """Un seul des deux fichiers est engendré, et il le dit : retouché à
    la main, la prochaine reconstruction effacerait la retouche sans
    prévenir. L'autre est la source, et ne doit surtout pas porter cet
    avertissement, sinon plus personne ne sait lequel éditer."""
    assert "FICHIER GÉNÉRÉ" in colors
    assert "scripts/build_theme.py" in colors
    assert "FICHIER GÉNÉRÉ" not in identity


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


def test_le_logo_est_servi_et_appele_par_le_calque(identity):
    """Le logo est posé en image de fond par le calque, pas en balise
    injectée dans le HTML de Swagger. Les deux moitiés doivent tenir
    ensemble : une URL relative dans la feuille, et une route qui répond
    à cette URL. Si l'une part sans l'autre, la page rend un titre sans
    logo, en silence."""
    assert 'url("inrae.svg")' in identity
    r = client.get("/static/inrae.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")


def test_l_onglet_porte_son_icone():
    """Sans favicon déclarée, la page arbore celle de FastAPI, qui n'est
    pas la nôtre. Elle est en URL `data:` échappée : non échappée, elle
    casserait sur le premier caractère non ASCII, ici l'émoji lui-même."""
    html = client.get("/docs").text
    assert "data:image/svg+xml," in html
    assert "fastapi" not in html.split("shortcut icon")[1][:200].lower()


def test_le_contrat_porte_ce_que_la_page_ne_montre_pas(identity):
    """Quatre champs sont MASQUÉS à l'écran : le résumé, qui redit la
    première phrase de la description, les conditions d'usage, qui
    pointent une section du README, et le contact et la licence, repris
    en fin de description sous la même forme que les autres liens.

    Masqué n'est pas supprimé, et c'est tout l'objet de ce test : un
    catalogue d'API affiche `summary` seul, un moissonneur lit la licence
    dans `openapi.json`, et ni l'un ni l'autre ne lit une description en
    prose. Ce qui coûte une ligne à l'écran ne coûte rien dans le
    contrat."""
    plat = identity.replace("\n", "")
    for bloc in ("info__summary", "info__tos", "info__contact",
                 "info__license"):
        assert bloc in plat, bloc
    info = client.get("/openapi.json").json()["info"]
    assert info["summary"].startswith("Variables hydroclimatiques")
    assert info["license"]["name"] == "GPL-3.0-or-later"
    assert info["contact"]["url"].endswith("card-api")
    assert "quotas" in info["termsOfService"]


def test_la_description_garde_sa_prose_et_ses_liens_a_part():
    """Un en-tête n'est pas un résumé du projet.

    Ce test ne fige PAS le nombre de blocs ni leur ordre : la mise en
    forme de l'en-tête se retouche souvent, et un test qui casse à chaque
    virgule déplacée finit par être contourné plutôt que lu. Il tient les
    deux invariants qui, eux, ne dépendent pas du goût du jour.

    1. La PROSE d'ouverture ne porte aucun lien. C'est le défaut d'origine
       (2026-07-27) : quatre liens semés au fil des phrases, et on ne
       savait plus si on lisait un texte ou un sommaire.
    2. Les trois chemins de contact restent atteignables : un bug, une
       demande de clé, un courriel. Sans eux, la page annonce un service
       public sans dire à qui s'adresser.
    """
    desc = client.get("/openapi.json").json()["info"]["description"]
    prose = desc.split("\n\n")[0]
    assert "](" not in prose, "un lien s'est glissé dans la prose"
    for chemin in ("/issues", "template=cle-de-priorite", "mailto:"):
        assert chemin in desc, chemin
