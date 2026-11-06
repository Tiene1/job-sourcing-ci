"""Orchestrateur du module 1 : collecte → scoring → détails → dédoublonnage → stockage.

python -m src.sourcing.main --config config.yaml --out out
Secrets optionnels (variables d'environnement) :
  GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID     → écriture Google Sheets
  GMAIL_USER, GMAIL_APP_PASSWORD           → alertes email (Emploi.ci, LinkedIn)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID     → notification de fin de run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import httpx
import yaml

from .core import Http, extract_email, score
from .sources import COLLECTORS

SHEET_COLUMNS = [
    "id", "date_detection", "source", "url", "entreprise", "titre", "lieu", "contrat",
    "mots_cles", "score", "email_contact", "date_pub", "date_limite", "statut",
]


# ------------------------------------------------------------ stockage
def existing_ids() -> set[str]:
    ws = _worksheet()
    return set(ws.col_values(1)[1:]) if ws else set()


def _worksheet():
    raw, sheet_id = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"), os.getenv("SHEET_ID")
    if not (raw and sheet_id):
        return None
    import gspread

    gc = gspread.service_account_from_dict(json.loads(raw))
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet("Candidatures")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Candidatures", rows=1000, cols=len(SHEET_COLUMNS))
    if ws.row_values(1) != SHEET_COLUMNS:
        ws.update([SHEET_COLUMNS], "A1")
    return ws


def save(rows: list[dict], out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "offres.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    ws = _worksheet()
    if ws and rows:
        ws.append_rows([[r.get(c, "") for c in SHEET_COLUMNS] for r in rows],
                       value_input_option="USER_ENTERED")   # une seule écriture groupée
        return "Google Sheets + CSV"
    return "CSV uniquement (secrets Sheets absents)"


def notify(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   data={"chat_id": chat, "text": text[:4000]}, timeout=20)


# ------------------------------------------------------------ pipeline
def run(cfg_path: Path, out: Path) -> None:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    http = Http(delay=cfg.get("delay_seconds", 2))
    known = existing_ids()
    stats, kept, seen_keys, errors = {}, [], set(), []

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
        good = [o for o in (score(o, cfg["scoring"]) for o in raw)
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
        o.email_contact = extract_email(o.description)
        if o.cle_doublon in seen_keys:
            continue
        seen_keys.add(o.cle_doublon)
        final.append(o)

    rows = []
    for o in final:
        r = o.to_row()
        r["statut"] = "Nouveau"
        rows.append(r)
    where = save(rows, out)

    lines = [f"Sourcing : {len(rows)} nouvelle(s) offre(s) pertinente(s) → {where}"]
    lines += [f"- {o.titre} | {o.entreprise or o.source} | score {o.score} | "
              f"{'email ✔' if o.email_contact else 'pas d’email'}\n  {o.url}" for o in final[:15]]
    if errors:
        lines.append("Erreurs : " + " ; ".join(errors))
    silent = [n for n, s in stats.items() if s["brutes"] == 0]
    if silent:
        lines.append("⚠️ Sources sans aucune offre brute : " + ", ".join(silent))
    summary = "\n".join(lines)
    print("\n" + summary)
    (out / "summary.json").write_text(json.dumps({"stats": stats, "errors": errors}, indent=2))
    notify(summary)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    p.add_argument("--out", type=Path, default=Path("out"))
    a = p.parse_args()
    run(a.config, a.out)
