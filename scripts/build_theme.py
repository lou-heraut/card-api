#!/usr/bin/env python3
"""Fabrique le thème sombre de `/docs` à partir du CSS réel de Swagger UI.

    python scripts/build_theme.py            # télécharge le CSS et construit
    python scripts/build_theme.py --css a.css  # depuis un fichier local

Pourquoi générer plutôt qu'écrire à la main. Swagger UI embarque 179 ko
de CSS, dont 726 déclarations de couleur. Une première tentative écrite
à la main (une centaine de règles, 2026-07-23) n'en recouvrait qu'une
fraction : fond sombre d'un côté, moitié des composants restés clairs,
résultat pire que le thème par défaut. On ne devine donc plus aucune
classe : on relit le CSS de Swagger, et pour CHAQUE règle qui pose une
couleur on ré-émet la même règle avec la couleur transposée. Sélecteurs
identiques, donc spécificité identique, donc c'est l'ordre de chargement
qui tranche, et le calque est chargé après.

Deux garde-fous, tous deux issus d'un défaut constaté à l'écran :
- une règle qui peint DÉJÀ une surface sombre est laissée intacte, sinon
  les blocs de code de Swagger (`pre.microlight{background:#333}`)
  repartent en clair avec leur texte blanc devenu noir ;
- le mode sombre natif de Swagger (`html.dark-mode`, jamais activé ici)
  est ignoré : le transposer n'ajoute que du bruit.

Ce que la substitution ne sait pas faire (gamme de gris, typographie,
gouttière, densité, états d'erreur) vit dans `scripts/theme-identity.css`,
concaténé après. Le résultat va dans `src/card_api/static/`, d'où une
route le sert.

Vérifier le résultat SE REGARDE, ça ne se déduit pas : voir la boucle de
capture d'écran décrite dans `docs/dev/THEME_DOCS.md`.
"""

import argparse
import colorsys
import pathlib
import re
import sys
import urllib.request

# Le CSS que sert FastAPI : même URL, même version majeure.
SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"

ROOT = pathlib.Path(__file__).resolve().parent.parent
IDENTITY = ROOT / "scripts" / "theme-identity.css"
TARGET = ROOT / "src" / "card_api" / "static" / "swagger-theme.css"

COLOR_PROPS = re.compile(
    r"^(color|background|background-color|background-image|border|border-\w+|"
    r"border-\w+-color|border-color|outline|outline-color|fill|stroke|"
    r"box-shadow|text-shadow|caret-color|-webkit-text-fill-color)$")

LIT = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b"
                 r"|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+\s*)?\)")

# Gamme neutre cible, volontairement OUVERTE : creux 0e, fond 13, bloc 1d,
# filet 38, texte ec. Ce sont les paliers qui font le relief ; tasser la
# gamme près du noir donne l'impression d'un filtre basse luminosité.
RAMP = [(0.00, 0.925), (0.20, 0.760), (0.35, 0.660), (0.50, 0.560),
        (0.65, 0.430), (0.80, 0.285), (0.90, 0.220), (0.95, 0.115),
        (1.00, 0.075)]

# Couleurs de méthode HTTP. Choisies pour rester distinctes en vision
# deutéranope : POST tire vers le bleu-vert, DELETE franchement vers
# l'orange. Et la couleur ne porte jamais l'information seule, le mot
# GET / POST / DELETE reste le repère.
EXACT = {
    "#61affe": "#8ab4dc",   # get
    "#49cc90": "#72b3a2",   # post
    "#f93e3e": "#e09b78",   # delete
    "#fca130": "#d9c07f",   # put
    "#50e3c2": "#8ab4dc",   # patch
    "#0d5aa7": "#8ab4dc", "#10a54a": "#72b3a2", "#a41e22": "#e09b78",
    "#b93900": "#d9c07f", "#3b8bbe": "#8ab4dc",
    "#4990e2": "#8ab4dc", "#51a8ff": "#8ab4dc",   # liens
    "#89bf04": "#72b3a2",   # pastille OAS
}

BANNER = """/* FICHIER GÉNÉRÉ : ne pas éditer à la main.
   Produit par `python scripts/build_theme.py`, qui transpose le CSS de
   Swagger UI ({src}) puis y ajoute `scripts/theme-identity.css`.
   Toute retouche se fait dans l'un de ces deux fichiers.
   Conception et façon de vérifier : docs/dev/THEME_DOCS.md */
"""


def parse_color(lit):
    """'#abc' | '#aabbcc' | 'rgba(1,2,3,.4)' -> (r, g, b, a)."""
    c = lit.strip().lower()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(x * 2 for x in h)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)
    n = [float(x) for x in c[c.index("(") + 1:c.index(")")].split(",")]
    return (n[0], n[1], n[2], n[3] if len(n) > 3 else 1.0)


def emit_color(r, g, b, a):
    r, g, b = (max(0, min(255, round(v))) for v in (r, g, b))
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r},{g},{b},{round(a, 3)})"


def on_ramp(x):
    for (x0, y0), (x1, y1) in zip(RAMP, RAMP[1:]):
        if x <= x1:
            t = 0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return RAMP[-1][1]


def remap(lit, prop):
    """Transpose une couleur du thème clair vers la gamme sombre."""
    key = lit.strip().lower()
    if key in EXACT:
        return EXACT[key]
    r, g, b, a = parse_color(lit)
    h, lightness, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    # Une ombre reste une ombre : inversée, elle deviendrait un halo.
    if "shadow" in prop:
        return emit_color(0, 0, 0, min(1.0, a * 1.7 if a < 1 else 0.45))
    if sat <= 0.10:                       # neutre : on retourne la gamme
        lightness, sat = on_ramp(lightness), 0.0
    else:                                 # chromatique : teinte gardée, pastel
        sat = min(sat, 0.48)
        lightness = 0.70 if lightness < 0.55 else max(0.58, min(lightness, 0.74))
    r2, g2, b2 = colorsys.hls_to_rgb(h, lightness, sat)
    return emit_color(r2 * 255, g2 * 255, b2 * 255, a)


def split_decls(body):
    """Découpe sur ';' en ignorant ceux placés dans une chaîne ou une
    parenthèse : une `url("data:image/svg+xml;charset=...")` en contient,
    et la couper laisse un guillemet ouvert qui avale la suite de la
    feuille. C'est ce qui avait fait échouer le premier essai."""
    out, cur, depth, quote = [], "", 0, None
    for ch in body:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    out.append(cur)
    return out


def iter_rules(css):
    """Itère (at-rules englobantes, sélecteur, déclarations), à plat."""
    out, stack, buf, i = [], [], "", 0
    while i < len(css):
        ch = css[i]
        if ch == "{":
            head, buf = buf.strip(), ""
            if head.startswith("@"):
                stack.append(head)
                i += 1
                continue
            depth, j = 1, i + 1
            while j < len(css) and depth:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            out.append((tuple(stack), head, css[i + 1:j - 1]))
            i = j
            continue
        if ch == "}":
            if stack:
                stack.pop()
            buf = ""
            i += 1
            continue
        buf += ch
        i += 1
    return out


def already_dark(body):
    """Une règle qui peint déjà une surface sombre est déjà habillée :
    l'inverser la rendrait claire, et son texte clair deviendrait
    sombre. Cas des blocs de code de Swagger, qui ressortaient
    illisibles."""
    for decl in split_decls(body):
        if ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        if prop.strip().lower() not in ("background", "background-color"):
            continue
        m = LIT.search(val)
        if not m:
            continue
        r, g, b, a = parse_color(m.group(0))
        if a > 0.5 and colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[1] < 0.32:
            return True
    return False


def transpose(src):
    """Le calque de couleurs, dérivé du CSS de Swagger."""
    lines, cur_at = [], None
    for ats, sel, body in iter_rules(re.sub(r"/\*.*?\*/", "", src, flags=re.S)):
        if "dark-mode" in sel or any("dark-mode" in a for a in ats):
            continue
        if already_dark(body):
            continue
        keep = []
        for decl in split_decls(body):
            if ":" not in decl:
                continue
            prop, val = decl.split(":", 1)
            prop, val = prop.strip().lower(), val.strip()
            if not COLOR_PROPS.match(prop) or not LIT.search(val):
                continue
            # Les images de fond (chevrons en data-URI) ne se transposent
            # pas par substitution : le calque d'identité les redessine.
            if val == "transparent" or "url(" in val:
                continue
            new = LIT.sub(lambda m: remap(m.group(0), prop), val)  # noqa: B023
            if new.lower() != val.lower():
                keep.append(f"{prop}:{new}")
        if not keep:
            continue
        # `@media screen and (a)and (b)` est invalide : Swagger minifie
        # sans l'espace, on le remet.
        at = re.sub(r"\)\s*and", ") and", " ".join(ats)) if ats else None
        if at != cur_at:
            if cur_at:
                lines.append("}")
            if at:
                lines.append(at + "{")
            cur_at = at
        lines.append(f"{sel}{{{';'.join(keep)}}}")
    if cur_at:
        lines.append("}")
    return "\n".join(lines)


def check(css):
    """Un thème qui ne se charge pas à moitié : garde-fou de syntaxe.
    Un guillemet non fermé fait avaler au navigateur tout ce qui suit,
    sans le moindre message. C'est arrivé, ça ne se voit qu'à l'écran.

    Les commentaires sont retirés d'abord : ils contiennent des
    apostrophes de prose et, pour l'un d'eux, un bloc de règles mis de
    côté."""
    code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert code.count("{") == code.count("}"), "accolades déséquilibrées"
    for quote in ("\"", "'"):
        assert code.count(quote) % 2 == 0, f"guillemet {quote} non fermé"
    depth = 0
    for line in code.splitlines():
        depth += line.count("{") - line.count("}")
        assert 0 <= depth <= 1, f"imbrication inattendue : {line[:70]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--css", help="CSS de Swagger local (défaut : téléchargé)")
    ap.add_argument("--out", default=str(TARGET))
    args = ap.parse_args()

    if args.css:
        src = pathlib.Path(args.css).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(SWAGGER_CSS, timeout=30) as r:
            src = r.read().decode("utf-8")

    css = "\n".join([BANNER.format(src=SWAGGER_CSS),
                     transpose(src),
                     IDENTITY.read_text(encoding="utf-8")])
    check(css)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(css, encoding="utf-8")
    print(f"{out.relative_to(ROOT)} : {len(css)} octets, "
          f"{css.count('{')} règles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
