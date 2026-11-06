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
        return hashlib.sha1(norm(self.url).encode()).hexdigest()[:12]

    @property
    def cle_doublon(self) -> str:
        """Même poste chez la même entreprise publié sur 2 sites."""
        if not self.entreprise:
            return self.id
        return hashlib.sha1(f"{norm(self.entreprise)}|{norm(self.titre)}".encode()).hexdigest()[:12]

    def to_row(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
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


def extract_email(text: str) -> str:
    bad = ("example", "sentry", "wixpress", ".png", ".jpg", "noreply", "no-reply")
    for m in EMAIL_RE.findall(text or ""):
        if not any(b in m.lower() for b in bad):
            return m
    return ""
