"""Appels IA gratuits : Gemini (Google AI Studio) puis Groq en secours. Réponse JSON."""

from __future__ import annotations

import json
import os
import time

import httpx

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(RuntimeError):
    pass


def _gemini(prompt: str, model: str, key: str) -> str:
    base = {"temperature": 0.4, "responseMimeType": "application/json"}
    variants = [dict(base, thinkingConfig={"thinkingLevel": "low"}),   # modèles récents : plus rapide
                dict(base, thinkingConfig={"thinkingBudget": 1024}),   # génération 2.5
                base]                                                   # sans réglage
    r = None
    for cfg in variants:
        r = httpx.post(
            GEMINI_URL.format(model=model), params={"key": key}, timeout=180,
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg},
        )
        if r.status_code == 400 and "thinking" in r.text.lower():
            continue                     # paramètre non supporté par ce modèle : variante suivante
        break
    if r.status_code != 200:
        raise LLMError(f"Gemini {model} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _groq(prompt: str, model: str, key: str) -> str:
    r = httpx.post(
        GROQ_URL, headers={"Authorization": f"Bearer {key}"}, timeout=120,
        json={
            "model": model, "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    if r.status_code != 200:
        raise LLMError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def generate_json(prompt: str, gemini_models: list[str], groq_model: str, groq_prompt: str | None = None) -> tuple[dict, str]:
    """Essaie chaque modèle Gemini puis Groq. Renvoie (json, modèle_utilisé)."""
    errors = []
    gkey, qkey = os.getenv("GEMINI_API_KEY"), os.getenv("GROQ_API_KEY")
    attempts = [("gemini", m) for m in gemini_models if gkey] + ([("groq", groq_model)] if qkey else [])
    if not attempts:
        raise LLMError("Aucune clé IA : ajoute le secret GEMINI_API_KEY (et GROQ_API_KEY en secours)")
    for provider, model in attempts:
        for retry in range(2):
            try:
                raw = _gemini(prompt, model, gkey) if provider == "gemini" else _groq(groq_prompt or prompt, model, qkey)
                return json.loads(raw.strip().removeprefix("```json").removesuffix("```"), strict=False), f"{provider}:{model}"
            except (LLMError, json.JSONDecodeError, KeyError, httpx.HTTPError) as exc:
                errors.append(str(exc)[:160])
                print(f"    [ia] {provider}:{model} a échoué → {type(exc).__name__}: {str(exc)[:300]}")
                if "429" in str(exc) and retry == 0:
                    time.sleep(30)  # quota minute dépassé : on attend une fois
                    continue
                break
    raise LLMError(" | ".join(errors))
