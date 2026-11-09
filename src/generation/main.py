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
from .profile import load_portfolio, load_profile
from . import prompt as prompt_mod
from .prompt import PROMPT_VERSION, build_design_prompt, build_prompt
from ..sourcing.core import Http, extract_email_html, lieu_autorise, valid_recruiter_email, zone_depuis


def run(cfg_path: Path) -> None:
    if not enabled():
        print("[génération] ignorée : secrets GOOGLE_SERVICE_ACCOUNT_JSON / SHEET_ID absents")
        return
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["generation"]
    store = Store()
    params = store.params()
    seuil = int(params.get("seuil_generation", cfg["seuil"]))
    maxi = int(params.get("max_generations_par_run", cfg["max_par_run"]))

    full_cfg0 = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    prompt_mod.CV_REFERENCE = full_cfg0.get("profil", {}).get("cv_reference_design") or prompt_mod.CV_REFERENCE
    _cleanup(store, zone_depuis(params, full_cfg0), full_cfg0.get("lieux_ambigus", []))
    _backfill_emails(store)
    def outdated(r):   # brouillon « À préparer » sans CV déposé, généré avec un ancien prompt
        return (r.get("statut") == "À préparer" and not r.get("cv_file_id")
                and f"Prompt {PROMPT_VERSION}" not in (r.get("notes") or ""))
    todo = [r for r in store.records()
            if (r.get("statut") == "Nouveau" and _int(r.get("score")) >= seuil) or outdated(r)]
    todo.sort(key=lambda r: -_int(r.get("score")))
    if not todo:
        print("[génération] rien à préparer")
        return

    profile = load_profile(store, {
        "CV": params.get("dossier_cv", cfg["dossier_cv"]),
        "LM": params.get("dossier_lm", cfg["dossier_lm"]),
    })
    full_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    profile["ZONE"] = ", ".join(zone_depuis(params, full_cfg)) or "la zone de recherche"
    prof = full_cfg.get("profil", {})
    profile["CANDIDAT"] = prof.get("nom", "")
    profile["DOMAINE"] = prof.get("domaine", "")
    profile["PAYS"] = prof.get("pays", "")
    purl = params.get("portfolio_url", cfg.get("portfolio_url", ""))
    try:
        profile["PORTFOLIO"], profile["PORTFOLIO_URL"] = load_portfolio(store, purl), purl
    except Exception as exc:
        print(f"  [profil] portfolio indisponible : {exc}")
    if not profile.get("CV"):
        msg = "Base_Profil/CV est vide : dépose au moins un CV pour activer la génération"
        print(f"[génération] {msg}")
        store.log("generation", msg)
        return

    ok = ko = hors = 0
    t0 = time.monotonic()
    for r in todo[:maxi]:
        if time.monotonic() - t0 > cfg.get("budget_minutes", 25) * 60:
            print("[génération] budget de temps atteint : la suite au prochain run")
            break
        try:
            data, model = generate_json(build_prompt(r, profile), cfg["gemini_models"], cfg["groq_model"],
                                        groq_prompt=build_prompt(r, profile, max_chars=9000))
        except LLMError as exc:
            ko += 1
            store.update(r["_row"], {"erreur": f"Génération : {exc}"[:500]})
            continue
        if data.get("dans_zone") is False:            # poste hors zone : on ne prépare rien
            store.update(r["_row"], {
                "statut": "Ignorée", "lieu": data.get("lieu") or r.get("lieu", ""), "erreur": "",
                "notes": f"Hors zone (IA) : {data.get('zone_raison', '')}"[:400],
                "date_preparation": now(),
            })
            hors += 1
            time.sleep(cfg.get("pause_s", 5))
            continue
        lettre = data.get("lettre", "")
        if not data.get("portfolio_pertinent"):        # garde-fou : pas de portfolio hors sujet
            lettre = _strip_portfolio(lettre)
        fields = {
            "adequation": data.get("adequation", ""),
            "points_forts": " • ".join(data.get("points_forts", [])),
            "contenu_cv": data.get("contenu_cv", ""),
            "prompt_claude_design": build_design_prompt(data.get("contenu_cv", "")),
            "objet_mail": data.get("objet_mail", ""),
            "lettre": lettre,
            "date_preparation": now(),
            "erreur": "",
            "statut": "À préparer",
            "notes": _notes(data, model),
        }
        for k in ("entreprise", "lieu", "contrat"):   # complète sans écraser
            if data.get(k) and not r.get(k):
                fields[k] = data[k]
        email = (data.get("email_contact") or "").strip()
        if not valid_recruiter_email(r.get("email_contact", "")):
            fields["email_contact"] = email if valid_recruiter_email(email) else ""
        store.update(r["_row"], fields)
        ok += 1
        time.sleep(cfg.get("pause_s", 5))   # respect du quota par minute

    msg = (f"{ok} candidature(s) préparée(s), {hors} hors zone ignorée(s), {ko} échec(s), "
           f"{max(0, len(todo) - maxi)} en file pour le prochain run")
    print(f"[génération] {msg}")
    store.log("generation", msg)


def _cleanup(store: Store, cibles: list[str] | None = None, ambigus: list[str] | None = None) -> None:
    """Corrige les lignes déjà en base : emails de sites ou invalides, prompts sans contenu,
    offres non envoyées dont le lieu connu est hors zone."""
    fixed = 0
    for r in store.records():
        fields = {}
        if (cibles and r.get("statut") in ("Nouveau", "À préparer") and not r.get("cv_file_id")
                and not lieu_autorise(r.get("lieu", ""), cibles, ambigus)):
            fields.update({"statut": "Ignorée", "notes": f"Hors zone : {r.get('lieu', '')}"})
        if r.get("email_contact") and not valid_recruiter_email(r["email_contact"]):
            fields["email_contact"] = ""
        if r.get("contenu_cv") and r.get("prompt_claude_design", "") != build_design_prompt(r["contenu_cv"]):
            fields["prompt_claude_design"] = build_design_prompt(r["contenu_cv"])   # gabarit à jour
        if fields and r.get("statut") in ("Nouveau", "À préparer", "Erreur envoi", "Test envoyé"):
            store.update(r["_row"], fields)
            fixed += 1
    if fixed:
        print(f"[génération] {fixed} ligne(s) corrigée(s) (emails de sites / prompts Claude Design)")
        store.log("generation", f"Nettoyage : {fixed} ligne(s) corrigée(s)")


def _backfill_emails(store: Store, limit: int = 25) -> None:
    """Relit la page des offres encore sans email (mailto, Cloudflare, texte) — sans IA."""
    http, found, checked = Http(delay=2), 0, 0
    for r in store.records():
        if checked >= limit:
            break
        if r.get("email_contact") or r.get("statut") not in ("Nouveau", "À préparer") or not r.get("url"):
            continue
        if "email non trouvé" in (r.get("notes") or ""):
            continue                       # déjà vérifiée : on ne refait pas la requête
        checked += 1
        try:
            email = extract_email_html(http.get(r["url"]))
        except Exception:
            continue
        if email:
            store.update(r["_row"], {"email_contact": email})
            found += 1
        else:
            store.update(r["_row"], {"notes": ((r.get("notes") or "") + " | email non trouvé sur la page de l'offre").strip(" |")})
    if checked:
        print(f"[génération] emails : {found} trouvé(s) sur {checked} offre(s) relue(s)")
        store.log("generation", f"Recherche d'emails : {found}/{checked} trouvé(s)")


def _strip_portfolio(text: str) -> str:
    """Retire toute phrase mentionnant le portfolio ou un lien vers celui-ci."""
    import re
    out = []
    for line in (text or "").split("\n"):
        parts = re.split(r"(?<=[.!?])\s+", line)
        keep = [p for p in parts if not re.search(r"portfolio|cedrictiene\.tech|https?://", p, re.I)]
        out.append(" ".join(keep))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _notes(data: dict, model: str) -> str:
    ecarts = data.get("ecarts") or []
    pf = "Portfolio cité" if data.get("portfolio_pertinent") else "Portfolio non cité"
    return (f"Prompt {PROMPT_VERSION} | Modèle : {model} | {pf} : {data.get('portfolio_raison', '')}"[:400]
            + (f" | Écarts : {' ; '.join(ecarts)}" if ecarts else ""))


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("config.yaml"))
    run(p.parse_args().config)
