# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Tableau de bord terminal du service.

    python -m card_api.stats            # instantané
    python -m card_api.stats --watch    # rafraîchi en continu

Lit le journal anonymisé (usage*.jsonl), l'état de la file de calcul
(data/jobs/) et le disque. Aucune dépendance : sparklines, heatmap
façon GitHub et barres en caractères Unicode.
"""

import argparse
import json
import shutil
import time
from collections import Counter
from datetime import date, timedelta

from . import jobs
from .hubeau import data_dir

SPARK = "▁▂▃▄▅▆▇█"
SHADE = "·░▒▓█"
W = 66                                  # largeur intérieure des cadres


# ── briques graphiques ───────────────────────────────────────────────────────

def _spark(values):
    top = max(values) if values and max(values) else 1
    out = []
    for v in values:
        out.append(" " if v == 0 else SPARK[max(0, min(7, round(v / top * 7)))])
    return "".join(out)


def _shade(v, top):
    if v == 0 or top == 0:
        return SHADE[0]
    return SHADE[max(1, min(4, round(v / top * 4)))]


def _bar(v, top, width=14):
    n = 0 if top == 0 else round(v / top * width)
    return "█" * n


def _box(title, lines):
    """Le cadre. Une ligne trop longue est coupée SUR UN POINT DE
    SUSPENSION : elle l'était silencieusement, et « ✗ 5 échecs » se
    lisait « ✗ 5 éc », c'est-à-dire un chiffre amputé qu'on croit
    complet. Couper reste un pis-aller, la vraie réponse est de ne pas
    fabriquer de ligne trop longue (cf. `_paquets`), mais le jour où l'une
    passe au travers, elle doit le dire."""
    out = [f"┌─ {title} " + "─" * max(0, W - len(title) - 1) + "┐"]
    for line in lines:
        if _width(line) > W:
            while _width(line) > W - 1:
                line = line[:-1]
            line += "…"
        out.append(f"│ {line}{' ' * (W - _width(line))} │")
    out.append("└" + "─" * (W + 2) + "┘")
    return "\n".join(out)


def _paquets(segments, sep="   "):
    """Range des segments en lignes qui tiennent dans le cadre.

    Les compteurs de la file étaient concaténés sans regarder la largeur :
    le jour où un échec est survenu, le mot a été tronqué. Le nombre de
    compteurs n'est pas fixe, donc aucune mise en forme figée ne tient ;
    il faut mesurer."""
    lignes, courante = [], ""
    for seg in segments:
        candidate = f"{courante}{sep}{seg}" if courante else seg
        if courante and _width(candidate) > W:
            lignes.append(courante)
            courante = seg
        else:
            courante = candidate
    if courante:
        lignes.append(courante)
    return lignes


def _width(s):
    """Largeur d'affichage (les pleins-chasses comptent double)."""
    return sum(2 if ord(c) > 0x2FFF else 1 for c in s)


def _fmt_size(n):
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024


# ── lecture des sources ──────────────────────────────────────────────────────

def _journal():
    entries = []           # usage*.jsonl : fichiers annuels + legacy
    for p in sorted(data_dir().glob("usage*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _per_day(entries, days):
    today = date.today()
    counts = {today - timedelta(d): 0 for d in range(days - 1, -1, -1)}
    for e in entries:
        try:
            d = date.fromisoformat(e["ts"][:10])
        except (KeyError, ValueError):
            continue
        if d in counts:
            counts[d] += 1
    return list(counts.values())


def _dir_size(path):
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# Listes FIXES, et non les endpoints rencontrés dans le journal. Une
# ligne qui n'apparaît que si le compteur est non nul se lit mal : on ne
# distingue plus « personne n'a appelé /v1/vocabulary » de « je ne sais
# pas », et le tableau change de forme d'un jour à l'autre, si bien qu'on
# cherche des yeux une ligne qu'on s'attendait à trouver. Un zéro est une
# information, souvent la plus utile : il dit qu'un endpoint qu'on
# maintient ne sert à personne.
ENDPOINTS_CALCUL = ("extract", "trend", "jobs")
ENDPOINTS_DECOUVERTE = ("cards", "card_detail", "card_figure",
                        "stations", "vocabulary", "suivi")
RENDUS = ("json", "csv", "figure")
GOUTTIERE = 13                          # colonne des libellés, commune


def _alias(nom):
    """`suivi` regroupe la gestion de ses propres jobs (liste, abandon).

    Ce n'est pas de la découverte du catalogue, mais ça passe par le même
    quota léger et donc par la même famille. Plutôt que d'inventer une
    troisième famille pour deux endpoints, on les montre à part DANS la
    découverte : le total reste juste et les cinq lignes du catalogue
    gardent leur sens, qui est de dire ce que les gens consultent.
    """
    return ("job_list", "job_delete") if nom == "suivi" else (nom,)


def _ligne(label, entries, indent=0):
    """Un libellé, sa courbe sur 30 jours, son total. Gouttière commune
    aux trois familles : c'est l'alignement qui rend deux courbes
    comparables d'un coup d'œil."""
    série = _per_day(entries, 30)
    return f"{' ' * indent + label:<{GOUTTIERE}} {_spark(série)} {sum(série):>5}"


def _detail(label, paires):
    """Une ligne de ventilation, alignée sur la même gouttière. Les zéros
    sont écrits : une représentation absente du décompte est justement ce
    qu'on veut voir."""
    return (f"{' ' * 2 + label:<{GOUTTIERE}} "
            + " · ".join(f"{n} {nom}" for nom, n in paires))


# ── cadres ───────────────────────────────────────────────────────────────────

def _activity_box(entries):
    # `event` exclut : un ÉVÉNEMENT n'est pas une requête. Le filtre ne
    # regardait que la présence d'`endpoint`, or `job_done` en porte un
    # (celui du traitement exécuté) : chaque job était donc compté deux
    # fois, au dépôt puis à sa fin, et la famille calcul surestimait
    # d'autant. Les refus de quota, ajoutés le 2026-07-29, tombent sous
    # la même règle et pour une raison plus forte encore : un utilisateur
    # repoussé n'a rien consommé.
    reqs = [e for e in entries if "endpoint" in e and "event" not in e]
    month = [e for e in reqs
             if e.get("ts", "")[:10] >= str(date.today() - timedelta(30))]
    # DEUX FAMILLES, jamais additionnées. Consulter le catalogue et
    # lancer un calcul sont deux usages réels mais d'un tout autre ordre
    # de grandeur : une somme unique serait écrasée par la découverte et
    # ne dirait plus rien du calcul. Les entrées d'avant le 2026-07-29
    # n'ont pas de famille et sont toutes du calcul, ce qu'elles étaient
    # (la découverte n'était pas journalisée).
    calcul = [e for e in reqs if e.get("famille") != "découverte"]
    decouverte = [e for e in reqs if e.get("famille") == "découverte"]
    refus = [e for e in entries
             if e.get("event") == "quota"
             and e.get("ts", "")[:10] >= str(date.today() - timedelta(30))]

    lines = [""]
    lines.append(_ligne("CALCUL", calcul))
    for nom in ENDPOINTS_CALCUL:
        lines.append(_ligne(nom, [e for e in calcul if e["endpoint"] == nom], 2))
    # Quelle REPRÉSENTATION a été demandée. Sans cette ligne, un CSV et
    # une figure se comptent comme du JSON : on ne saurait jamais si ces
    # deux sorties, ajoutées le 2026-07-28, servent à quelqu'un. Les
    # entrées d'avant cette date n'ont pas le champ, d'où le défaut.
    rendus = Counter(e.get("rendu", "json") for e in month
                     if e["endpoint"] in ("extract", "trend"))
    lines.append(_detail("rendu", [(n, rendus.get(n, 0)) for n in RENDUS]))

    lines.append("")
    lines.append(_ligne("DÉCOUVERTE", decouverte))
    for nom in ENDPOINTS_DECOUVERTE:
        sel = [e for e in decouverte if e["endpoint"] in _alias(nom)]
        lines.append(_ligne(nom, sel, 2))

    # Les REFUS de quota, TOUJOURS affichés, zéro compris. Un plafond qui
    # ne mord pas est une information, et c'est même celle qu'on espère :
    # la ligne absente, on ne sait pas distinguer « personne n'a été
    # repoussé » de « je ne sais pas ». Le chiffre qui permet de régler
    # les plafonds n'est pas le total mais le nombre de personnes
    # DISTINCTES : une personne bloquée trente fois est un script mal
    # écrit, à qui il faut expliquer la liste ; trente personnes bloquées
    # une fois est un plafond trop bas.
    lines.append("")
    lines.append(_ligne("REFUS", refus))
    par_famille = Counter(e.get("famille", "?") for e in refus)
    bloqués = len({e["user"] for e in refus if "user" in e})
    lines.append(_detail("dont", [(f, par_famille.get(f, 0))
                                  for f in ("calcul", "découverte")]
                         + [("IP distinctes", bloqués)]))

    users = len({e["user"] for e in month if "user" in e})
    lines += ["", f"30 jours · {len(month)} requêtes · "
                  f"{users} utilisateurs (IP hachées)", ""]

    # heatmap 12 semaines (colonnes = semaines, lignes = jours)
    today = date.today()
    start = today - timedelta(days=today.weekday() + 7 * 11)
    per_day = Counter(e["ts"][:10] for e in reqs if "ts" in e)
    top = max((per_day[str(start + timedelta(w * 7 + d))]
               for w in range(12) for d in range(7)), default=0)
    names = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    for d in range(7):
        row = " ".join(
            _shade(per_day[str(start + timedelta(w * 7 + d))], top)
            for w in range(12))
        lines.append(f"{names[d]}  {row}")
    lines.append("")

    cards = Counter(c for e in month for c in e.get("cards", []))
    top_c = cards.most_common(3)
    best = top_c[0][1] if top_c else 0
    lines.append("fiches  " + ("   ".join(
        f"{name} {_bar(n, best, 8)} {n}" for name, n in top_c)
        if top_c else "aucune demandée sur la période"))
    return _box("card-api · activité", lines)


def _jobs_box(entries):
    q = jobs.queue_stats()
    today = str(date.today())
    done = [e for e in entries if e.get("event") == "job_done"]
    done_today = [e for e in done if e.get("ts", "")[:10] == today]
    failed_today = [e for e in done_today if e.get("status") == "failed"]
    # Les échecs sont TOUJOURS comptés, zéro compris : une journée sans
    # échec est précisément ce qu'on vient vérifier, et une ligne qui
    # n'apparaît qu'en cas de problème ne permet pas de le constater.
    lines = _paquets([f"● {q['running']} en cours",
                      f"○ {q['queued']} en attente",
                      f"✓ {len(done_today)} terminés aujourd'hui",
                      f"✗ {len(failed_today)} échecs"])

    waits = sorted(e["wait_s"] for e in done[-200:] if "wait_s" in e)
    if waits:
        p95 = waits[min(len(waits) - 1, int(0.95 * len(waits)))]
        runs = sorted(e["run_s"] for e in done[-200:] if "run_s" in e)
        p50r = runs[len(runs) // 2] if runs else 0
        lines.append(f"attente p95 : {p95:.0f} s   calcul médian : {p50r:.0f} s")

    for d in sorted(jobs.jobs_dir().iterdir()):
        job = jobs.load(d.name)
        if job is None or job["status"] != "running":
            continue
        pr = job["progress"]
        total = max(pr.get("total", 1), 1)
        frac = pr.get("done", 0) / total
        bar = "▓" * round(frac * 12) + "░" * (12 - round(frac * 12))
        p = job["params"]
        lines.append(f"#{job['id']}  {p['endpoint']:<7} "
                     f"{len(p['stations']):>4} st × {len(p['cards'])} fiches  "
                     f"{bar} {frac:>4.0%}  {pr.get('phase', '')[:18]}")

    du = shutil.disk_usage(data_dir())
    lines.append(
        f"disque {du.used / du.total:.0%} ({du.free / 1e9:.0f} Go libres)"
        f" · cache {_fmt_size(_dir_size(data_dir() / 'chroniques'))}"
        f" · résultats {_fmt_size(_dir_size(jobs.jobs_dir()))}")
    return _box("file de calcul", lines)


def render() -> str:
    entries = _journal()
    return _activity_box(entries) + "\n" + _jobs_box(entries)


def main():
    parser = argparse.ArgumentParser(description="tableau de bord card-api")
    parser.add_argument("--watch", action="store_true",
                        help="rafraîchit toutes les 2 s (Ctrl-C pour sortir)")
    args = parser.parse_args()
    if not args.watch:
        print(render())
        return
    try:
        while True:
            print("\x1b[2J\x1b[H" + render(), flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
