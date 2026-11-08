"""Briques communes : modèle Offre, client HTTP poli, scoring, dédoublonnage."""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-CI,fr;q=0.9,en;q=0.6",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


LINKEDIN_JOB_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.I)


def canonical_url(url: str) -> str:
    """URL stable d'une offre : supprime les paramètres de suivi (trackingId, refId…).
    Une même offre LinkedIn reçue dans 2 alertes donne ainsi le même id."""
    m = LINKEDIN_JOB_RE.search(url or "")
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    return url or ""


def cle_doublon(entreprise: str, titre: str, fallback: str) -> str:
    """Même poste chez la même entreprise publié sur 2 sites (ou reçu 2 fois)."""
    if not norm(entreprise):
        return fallback
    return hashlib.sha1(f"{norm(entreprise)}|{norm(titre)}".encode()).hexdigest()[:12]


def lieu_autorise(lieu: str, cibles: list[str]) -> bool:
    """Vrai si le lieu est vide (inconnu) ou contient une des localités cibles."""
    l = norm(lieu)
    return not l or any(re.search(rf"(?<![a-z]){re.escape(norm(c))}(?![a-z])", l) for c in cibles)


# ------------------------------------------------------------------ modèle
@dataclass
class Offre:
    source: str
    url: str
    titre: str
    entreprise: str = ""
    lieu: str = ""
    contrat: str = ""
    date_pub: str = ""
    date_limite: str = ""
    description: str = ""
    email_contact: str = ""
    mots_cles: list[str] = field(default_factory=list)
    score: int = 0
    date_detection: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    )

    @property
    def id(self) -> str:
        return hashlib.sha1(norm(canonical_url(self.url)).encode()).hexdigest()[:12]

    @property
    def cle_doublon(self) -> str:
        return cle_doublon(self.entreprise, self.titre, self.id)

    def to_row(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["url"] = canonical_url(self.url)
        d["mots_cles"] = ", ".join(self.mots_cles)
        return d


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ------------------------------------------------------------------ HTTP
class Http:
    def __init__(self, delay: float = 2.0):
        self.client = httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True)
        self.delay = delay

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20), reraise=True)
    def get(self, url: str) -> str:
        time.sleep(self.delay)
        r = self.client.get(url)
        r.raise_for_status()
        return r.text

    def soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.get(url), "html.parser")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def card_of(a, min_len: int = 30, max_len: int = 700):
    """Remonte depuis un lien d'offre jusqu'au bloc 'carte' qui la décrit."""
    node = a
    for _ in range(5):
        if node.parent is None:
            break
        node = node.parent
        n = len(clean(node.get_text(" ")))
        if min_len <= n <= max_len:
            return node
    return a.parent


# ------------------------------------------------------------------ scoring
def score(offre: Offre, cfg: dict) -> Offre:
    title, body = norm(offre.titre), norm(f"{offre.description} {offre.entreprise}")
    mult = cfg.get("title_multiplier", 3)
    total, hits = 0, []
    for kw, w in {**cfg["positive"], **cfg["negative"]}.items():
        k = norm(kw)
        pat = re.compile(rf"\b{re.escape(k)}(?:s|e|es|ne|nes)?\b")
        if pat.search(title):
            total += w * mult
            hits.append(kw)
        elif pat.search(body):
            total += w
            if w > 0:
                hits.append(kw)
    offre.score, offre.mots_cles = total, hits
    return offre


# Domaines des sites d'emploi / plateformes : leurs emails ne sont JAMAIS ceux du recruteur
SITE_DOMAINS = ("educarriere", "jobivoire", "novojob", "emploi.ci", "linkedin", "indeed",
                "example", "sentry", "wixpress", "google.com", "gstatic", "w3.org", "schema.org")
BAD_LOCAL = ("noreply", "no-reply", "donotreply", "plainte", "webmaster", "support@", "contact@educarriere")


def valid_recruiter_email(e: str) -> bool:
    e = (e or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", e):
        return False
    if e.endswith((".png", ".jpg", ".gif", ".webp")):
        return False
    return not any(d in e.split("@")[1] for d in SITE_DOMAINS) and not any(b in e for b in BAD_LOCAL)


def _cf_decode(hexstr: str) -> str:
    """Décode une adresse protégée par Cloudflare (data-cfemail / /cdn-cgi/l/email-protection#...)."""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""


def emails_from_html(html: str) -> list[str]:
    """Toutes les adresses candidates d'une page, dans l'ordre : mailto, Cloudflare, texte."""
    found: list[str] = []
    for m in re.findall(r"mailto:([^\"'?>\s]+)", html or "", re.I):
        found.append(m)
    for h in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html or ""):
        found.append(_cf_decode(h))
    for h in re.findall(r'/cdn-cgi/l/email-protection#([0-9a-fA-F]+)', html or ""):
        d = _cf_decode(h)
        if "?" not in d:          # les liens « partager par email » contiennent ?subject=
            found.append(d)
    text = re.sub(r"\s*[\[(]\s*(?:at|arobase)\s*[\])]\s*", "@", html or "", flags=re.I)
    found += EMAIL_RE.findall(text)
    return found


def extract_email_html(html: str) -> str:
    for e in emails_from_html(html):
        e = e.strip().strip(".")
        if valid_recruiter_email(e):
            return e
    return ""


def extract_email(text: str) -> str:
    for m in EMAIL_RE.findall(text or ""):
        if valid_recruiter_email(m):
            return m
    return ""
