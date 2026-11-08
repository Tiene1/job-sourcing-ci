"""Orchestrateur du module 1 : collecte → scoring → détails → dédoublonnage → stockage.

python -m src.sourcing.main --config config.yaml --out out
Secrets optionnels (variables d'environnement) :
  GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID     → écriture Google Sheets
  GMAIL_USER, GMAIL_APP_PASSWORD           → alertes email (Emploi.ci, LinkedIn)
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import yaml

from ..common.store import Store, enabled
from .core import Http, Offre, cle_doublon, extract_email, lieu_autorise, score, zone_depuis
from .sources import COLLECTORS

CSV_COLUMNS = ["id", "date_detection", "source", "url", "entreprise", "titre", "lieu",
               "contrat", "mots_cles", "score", "email_contact", "date_pub", "date_limite", "statut"]


# ------------------------------------------------------------ stockage
def save(rows: list[dict], out: Path, store) -> str:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "offres.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    if store:
        store.append(rows)   # une seule écriture groupée
        return "Google Sheets + CSV"
    return "CSV uniquement (secrets Google absents)"


# ------------------------------------------------------------ pipeline
def run(cfg_path: Path, out: Path) -> None:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    http = Http(delay=cfg.get("delay_seconds", 2))
    store = Store() if enabled() else None
    # déjà en base : ids (recalculés sur l'URL canonique) + clés entreprise|titre (offre vue sur un autre site)
    known, seen_keys = set(), set()
    if store:
        for r in store.records():
            if not r.get("id"):
                continue
            known.add(r["id"])
            known.add(Offre(source="", url=r.get("url", ""), titre="").id)
            seen_keys.add(cle_doublon(r.get("entreprise", ""), r.get("titre", ""), r["id"]))
    cibles = zone_depuis(store.params() if store else {}, cfg)
    ambigus = cfg.get("lieux_ambigus", [])
    stats, kept, errors = {}, [], []
    hors_zone = 0

    for name, scfg in cfg["sources"].items():
        if not scfg.get("enabled"):
            continue
        collect, detail = COLLECTORS[name]
        try:
            raw = collect(http, scfg)
        except Exception as exc:          # une source en panne n'arrête pas les autres
            errors.append(f"{name}: {type(exc).__name__}: {exc}"[:200])
            stats[name] = {"brutes": 0, "gardees": 0, "erreur": True}
            continue
        dans_zone = [o for o in raw if not cibles or lieu_autorise(o.lieu, cibles, ambigus)]
        hors_zone += len(raw) - len(dans_zone)
        good = [o for o in (score(o, cfg["scoring"]) for o in dans_zone)
                if o.score >= cfg["scoring"]["threshold"] and o.id not in known]
        stats[name] = {"brutes": len(raw), "gardees": len(good), "erreur": False}
        kept.extend((o, detail) for o in good)
        print(f"[{name}] {len(raw)} offres brutes → {len(good)} pertinentes et nouvelles")

    # fiches détaillées : description complète + email de contact
    budget = cfg.get("max_details_per_run", 40)
    final = []
    for o, detail in sorted(kept, key=lambda t: -t[0].score):
        if detail and budget > 0:
            budget -= 1
            try:
                detail(http, o)   # le score initial (titre + carte) est conservé
            except Exception as exc:
                errors.append(f"détail {o.url}: {type(exc).__name__}"[:200])
        o.email_contact = o.email_contact or extract_email(o.description)
        if cibles and not lieu_autorise(o.lieu, cibles, ambigus):   # lieu connu seulement après la fiche détaillée
            hors_zone += 1
            continue
        if o.cle_doublon in seen_keys:
            continue
        seen_keys.add(o.cle_doublon)
        final.append(o)

    rows = []
    for o in final:
        r = o.to_row()
        r["statut"] = "Nouveau"
        rows.append(r)
    where = save(rows, out, store)

    lines = [f"Sourcing : {len(rows)} nouvelle(s) offre(s) pertinente(s) → {where}"]
    lines += [f"- {o.titre} | {o.entreprise or o.source} | score {o.score} | "
              f"{'email ✔' if o.email_contact else 'pas d’email'}\n  {o.url}" for o in final[:15]]
    detail_sources = " · ".join(f"{n} {s['brutes']}→{s['gardees']}" for n, s in stats.items())
    lines.append(f"Sources (brutes→retenues) : {detail_sources}" + (f" · {hors_zone} hors zone écartée(s)" if hors_zone else ""))
    if errors:
        lines.append("Erreurs : " + " ; ".join(errors))
    silent = [n for n, s in stats.items() if s["brutes"] == 0]
    if silent:
        lines.append("⚠️ Sources sans aucune offre brute : " + ", ".join(silent))
    summary = "\n".join(lines)
    print("\n" + summary)
    (out / "summary.json").write_text(json.dumps({"stats": stats, "errors": errors}, indent=2))
    if store:
        store.log("sourcing", " | ".join([lines[0], next(l for l in lines if l.startswith("Sources"))]
                                          + ([lines[-1]] if errors or silent else [])))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--out", type=Path, default=Path("out"))
    a = p.parse_args()
    run(a.config, a.out)
