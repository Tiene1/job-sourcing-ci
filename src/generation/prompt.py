"""Prompt de génération : une offre + la base profil → contenu CV, prompt Claude Design, lettre."""

PROMPT_VERSION = "v5"

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
6. CONSOLIDE : les différents CV et le portfolio décrivent la même personne sous plusieurs angles.
   Croise-les pour retrouver, pour chaque expérience, TOUTES les missions, outils, équipements,
   normes et résultats mentionnés quelque part dans la base, puis garde les plus pertinents pour l'offre.

7. FIDÉLITÉ DES FAITS VÉRIFIABLES : intitulés de poste, noms d'entreprises, lieux, dates, diplômes
   et noms de projets sont repris EXACTEMENT tels qu'écrits dans la base. Si plusieurs CV donnent
   des intitulés différents pour le même poste, choisis l'une de ces variantes existantes (la plus
   proche de l'offre) — n'en fabrique jamais une nouvelle. Les missions décrivent uniquement ce
   que la base dit réellement de ce poste (reformulation autorisée, ajout de tâches interdit).

# RÈGLES DE RÉDACTION DU CV (exigence d'un recruteur technique industriel)
- EXPÉRIENCES : pour chaque poste retenu, 3 à 4 missions (jamais moins de 3 si la base le permet),
  classées de la plus pertinente à la moins pertinente pour l'offre.
- Chaque mission = verbe d'action technique au passé composé ou à l'infinitif (Installer, Câbler,
  Paramétrer, Programmer, Diagnostiquer, Étalonner, Mettre en service, Superviser, Dépanner,
  Rédiger…) + objet technique précis (équipement, système, protocole, logiciel, marque, norme)
  + contexte ou périmètre (nb de sites, type d'installation, client) + résultat concret si la base
  le mentionne. Une ligne, 15 à 30 mots, sans phrase vague (« participer à », « divers travaux »).
- Emploie le VOCABULAIRE MÉTIER exact de l'offre et du domaine (ex. instrumentation, boucle
  4-20 mA, capteurs/transmetteurs, étalonnage, régulation PID, automate/API Siemens S7-1200,
  TIA Portal, GRAFCET, schémas électriques, armoire/coffret, consignation, maintenance préventive
  et corrective, diagnostic de pannes, GMAO, mise en service, réseaux industriels, supervision)
  UNIQUEMENT quand le fait correspondant existe dans la base.
- FORMAT DES MISSIONS (comme mes CV de référence) : chaque puce commence par un libellé court en
  gras suivi de deux-points, puis la mission. Ex. « **Installation :** déploiement d'équipements
  électroniques sur 8 sites (alimentation électrique, câblage, coffrets, mise en service). »
  Libellés typiques : Installation, Mise en service, Diagnostic & maintenance, Programmation,
  Étalonnage & qualification, Chaîne de mesure, Acquisition, Supervision, Intégration IT/OT,
  Préparation & traçabilité, Sécurité.
- SECTION « RÉALISATIONS » : OBLIGATOIRE dès qu'au moins un projet de la base (sections
  « Réalisations » / « Projets » des CV, ou projets du portfolio) est en lien avec l'offre
  (même domaine technique, mêmes outils, même type d'équipement). Mets 2 à 3 réalisations, les
  plus proches de l'offre d'abord, au format :
  « **Nom du projet (année) :** ce qui a été réalisé, avec les technologies/équipements précis. »
  Ex. « **Automatisation d'une station d'épuration (2023) :** programmation d'automates Siemens
  S7-300/1200 sous TIA Portal, paramétrage des variables de procédé (niveaux, débits, cycles) et
  IHM de supervision sous WinCC. »
  N'invente aucun projet ; si aucun projet n'est pertinent, omets la section.
- Compétences regroupées par familles (ex. Automatisme & instrumentation · Électricité industrielle
  · Maintenance · Réseaux & IoT · Outils/logiciels), mots-clés de l'offre en premier.
- Titre du CV = intitulé du poste visé (adapté), profil de 3 lignes orienté valeur pour l'employeur.

# OFFRE
Titre : {titre}
Source : {source} — {url}
Date limite : {date_limite}
Texte de l'offre :
{description}

# BASE PROFIL — CV (du plus récent au plus ancien)
{cv}

# BASE PROFIL — PORTFOLIO (projets réels, source : {portfolio_url})
{portfolio}

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
  "portfolio_pertinent": false,
  "portfolio_raison": "pourquoi le portfolio apporte (ou non) une preuve utile pour CETTE offre",
  "lettre": "Corps du mail = lettre de motivation (180 à 260 mots) : formule d'appel, accroche liée à l'entreprise/au poste, 2 paragraphes de preuves tirées de la base, disponibilité, mention du CV en pièce jointe, formule de politesse, signature avec nom et téléphone tels que dans la base."
}}
LIEN PORTFOLIO : "portfolio_pertinent" = true UNIQUEMENT si au moins un projet du portfolio
prouve directement une compétence demandée par l'offre (ex. offre IoT, développement, supervision,
systèmes connectés). Pour une offre de maintenance, d'électricité ou d'électromécanique sans lien
avec ces projets : false. Si false, la lettre ne doit contenir AUCUN lien ni mention du portfolio.
Si true, mentionne-le en une phrase qui cite le projet concerné, avec le lien {portfolio_url}.
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
        portfolio=(profile.get("PORTFOLIO") or "(non disponible)")[: max_chars // 2],
        portfolio_url=profile.get("PORTFOLIO_URL", ""),
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
