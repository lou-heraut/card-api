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

Lit le journal anonymisé (usage.jsonl), l'état de la file de calcul
(data/jobs/) et le disque. Aucune dépendance : sparklines, heatmap
façon GitHub et barres en caractères Unicode.
"""

import argparse
import json
import shutil
import time
from collections import Counter
from datetime import date, datetime, timedelta

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
    out = [f"┌─ {title} " + "─" * max(0, W - len(title) - 1) + "┐"]
    for line in lines:
        while _width(line) > W:
            line = line[:-1]
        out.append(f"│ {line}{' ' * (W - _width(line))} │")
    out.append("└" + "─" * (W + 2) + "┘")
    return "\n".join(out)


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
    p = data_dir() / "usage.jsonl"
    entries = []
    if p.exists():
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


# ── cadres ───────────────────────────────────────────────────────────────────

def _activity_box(entries):
    reqs = [e for e in entries if "endpoint" in e]
    month = [e for e in reqs
             if e.get("ts", "")[:10] >= str(date.today() - timedelta(30))]
    lines = [""]
    for label, sel in (("requêtes", reqs),
                       ("extract ", [e for e in reqs if e["endpoint"] == "extract"]),
                       ("trend   ", [e for e in reqs if e["endpoint"] == "trend"]),
                       ("jobs    ", [e for e in reqs if e["endpoint"] == "jobs"])):
        série = _per_day(sel, 30)
        n_month = sum(série)
        lines.append(f"{label}  {_spark(série)}  {n_month:>5}")
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
    if cards:
        top_c = cards.most_common(3)
        best = top_c[0][1]
        lines.append("fiches  " + "   ".join(
            f"{name} {_bar(n, best, 8)} {n}" for name, n in top_c))
    return _box("card-api · activité", lines)


def _jobs_box(entries):
    q = jobs.queue_stats()
    today = str(date.today())
    done = [e for e in entries if e.get("event") == "job_done"]
    done_today = [e for e in done if e.get("ts", "")[:10] == today]
    failed_today = [e for e in done_today if e.get("status") == "failed"]
    lines = [f"● {q['running']} en cours   ○ {q['queued']} en attente   "
             f"✓ {len(done_today)} terminés aujourd'hui"
             + (f"   ✗ {len(failed_today)} échecs" if failed_today else "")]

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
