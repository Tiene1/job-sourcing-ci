"""Prompt de génération : une offre + la base profil → contenu CV, prompt Claude Design, lettre."""

PROMPT = """Tu es un conseiller en recrutement spécialisé dans l'industrie (instrumentation, automatisme,
maintenance industrielle) en Côte d'Ivoire. Tu prépares la candidature de Cédric.

# RÈGLES ABSOLUES
1. Utilise UNIQUEMENT les faits présents dans la BASE PROFIL ci-dessous. N'invente jamais une
   expérience, une entreprise, un diplôme, une durée, un chiffre ou une compétence.
2. Si l'offre demande une compétence absente de la base, ne la revendique pas : valorise plutôt
   une compétence proche réellement présente (et dis-le dans "ecarts").
3. Réordonne et reformule pour coller au vocabulaire de l'offre (mots-clés industriels).
4. Français professionnel, sobre, sans formules creuses.
5. Les lettres de la base servent de référence de TON et de STRUCTURE, pas de texte à copier.

# OFFRE
Titre : {titre}
Source : {source} — {url}
Date limite : {date_limite}
Texte de l'offre :
{description}

# BASE PROFIL — CV (du plus récent au plus ancien)
{cv}

# BASE PROFIL — LETTRES DE MOTIVATION DE RÉFÉRENCE
{lm}

# CE QUE TU DOIS RENVOYER (JSON strict, clés exactes)
{{
  "entreprise": "nom de l'entreprise qui recrute, ou '' si absent",
  "email_contact": "adresse email OÙ ENVOYER LA CANDIDATURE, écrite telle quelle dans l'offre (ex. rh@entreprise.ci). '' si absente. Jamais l'email du site d'annonces (educarriere, jobivoire, novojob, emploi.ci), jamais un nom de site, jamais une adresse inventée",
  "lieu": "ville / site, ou ''",
  "contrat": "CDI / CDD / Stage / Intérim / '' ",
  "exigences": ["5 à 8 exigences clés de l'offre"],
  "adequation": 0,
  "points_forts": ["3 à 5 correspondances concrètes profil ↔ offre"],
  "ecarts": ["exigences non couvertes par le profil"],
  "contenu_cv": "Contenu complet du CV adapté, en Markdown : En-tête (nom, titre ciblé sur le poste, contacts tels que dans la base) ; Profil (3 lignes) ; Compétences clés (ordonnées selon l'offre) ; Expériences (rôles réels, puces orientées résultats, vocabulaire de l'offre) ; Formation ; Certifications ; Langues. Doit tenir sur UNE page A4.",
  "objet_mail": "Si l'offre IMPOSE un objet (ex. « Objet de candidature : RECRUTEMENT … » ou « mentionner la référence … en objet »), reprends-le EXACTEMENT. Sinon : Candidature – <intitulé exact du poste> – <référence de l'offre si présente> – Yoma Paul Cédric TIENE",
  "lettre": "Corps du mail = lettre de motivation (180 à 260 mots) : formule d'appel, accroche liée à l'entreprise/au poste, 2 paragraphes de preuves tirées de la base, disponibilité, mention du CV en pièce jointe, formule de politesse, signature avec nom et téléphone tels que dans la base."
}}
"adequation" est un entier de 0 à 100 (honnête : correspondance réelle entre l'offre et le profil).
"""


def build_prompt(offre: dict, profile: dict, max_chars: int = 60000) -> str:
    """max_chars réduit (≈12000) pour Groq dont le quota gratuit est de 8 000 tokens/minute."""
    return PROMPT.format(
        titre=offre.get("titre", ""), source=offre.get("source", ""), url=offre.get("url", ""),
        date_limite=offre.get("date_limite", "") or "non précisée",
        description=(offre.get("description") or "")[:8000],
        cv=(profile.get("CV") or "(aucun CV dans Base_Profil/CV)")[:max_chars],
        lm=(profile.get("LM") or "(aucune lettre de référence)")[: max_chars // 3],
    )


DESIGN_PROMPT = """Crée mon CV en respectant STRICTEMENT ces consignes :
- Format A4, UNE seule page, UNE seule colonne, style sobre et professionnel, identique à mes CV précédents.
- Hiérarchie claire : nom en en-tête, titre du poste visé, coordonnées, puis sections avec titres distincts.
- Police lisible, marges équilibrées, aucune photo, aucune icône décorative superflue.
- Reprends le contenu ci-dessous INTÉGRALEMENT et MOT POUR MOT : n'ajoute, ne retire et n'invente rien.
- Livre le résultat prêt à exporter en PDF.

=== CONTENU DU CV ===
{contenu}
"""


def build_design_prompt(contenu_cv: str) -> str:
    return DESIGN_PROMPT.format(contenu=(contenu_cv or "").strip())
