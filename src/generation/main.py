"""Module 2 — Génération : pour chaque offre 'Nouveau' au-dessus du seuil, prépare
contenu CV + prompt Claude Design + objet + lettre, puis passe le statut à 'À préparer'.

python -m src.generation.main --config config.yaml
Secrets : GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_ID, GEMINI_API_KEY (GROQ_API_KEY en secours)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml

from ..common.store import Store, enabled, now
from .llm import LLMError, generate_json
from .profile import load_profile
from .prompt import build_prompt


def run(cfg_path: Path) -> None:
    if not enabled():
        print("[génération] ignorée : secrets GOOGLE_SERVICE_ACCOUNT_JSON / SHEET_ID absents")
        return
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["generation"]
    store = Store()
    params = store.params()
    seuil = int(params.get("seuil_generation", cfg["seuil"]))
    maxi = int(params.get("max_generations_par_run", cfg["max_par_run"]))

    todo = [r for r in store.records()
            if r.get("statut") == "Nouveau" and _int(r.get("score")) >= seuil]
    todo.sort(key=lambda r: -_int(r.get("score")))
    if not todo:
        print("[génération] rien à préparer")
        return

    profile = load_profile(store, {
        "CV": params.get("dossier_cv", cfg["dossier_cv"]),
        "LM": params.get("dossier_lm", cfg["dossier_lm"]),
    })
    if not profile.get("CV"):
        msg = "Base_Profil/CV est vide : dépose au moins un CV pour activer la génération"
        print(f"[génération] {msg}")
        store.log("generation", msg)
        return

    ok = ko = 0
    for r in todo[:maxi]:
        try:
            data, model = generate_json(build_prompt(r, profile), cfg["gemini_models"], cfg["groq_model"])
        except LLMError as exc:
            ko += 1
            store.update(r["_row"], {"erreur": f"Génération : {exc}"[:500]})
            continue
        fields = {
            "adequation": data.get("adequation", ""),
            "points_forts": " • ".join(data.get("points_forts", [])),
            "contenu_cv": data.get("contenu_cv", ""),
            "prompt_claude_design": data.get("prompt_claude_design", ""),
            "objet_mail": data.get("objet_mail", ""),
            "lettre": data.get("lettre", ""),
            "date_preparation": now(),
            "erreur": "",
            "statut": "À préparer",
            "notes": _notes(data, model),
        }
        for k in ("entreprise", "email_contact", "lieu", "contrat"):   # complète sans écraser
            if data.get(k) and not r.get(k):
                fields[k] = data[k]
        store.update(r["_row"], fields)
        ok += 1
        time.sleep(cfg.get("pause_s", 5))   # respect du quota par minute

    msg = f"{ok} candidature(s) préparée(s), {ko} échec(s), {max(0, len(todo) - maxi)} en file pour le prochain run"
    print(f"[génération] {msg}")
    store.log("generation", msg)


def _notes(data: dict, model: str) -> str:
    ecarts = data.get("ecarts") or []
    return f"Modèle : {model}" + (f" | Écarts : {' ; '.join(ecarts)}" if ecarts else "")


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    run(p.parse_args().config)
