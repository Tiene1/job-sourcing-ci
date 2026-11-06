"""Diagnostic d'accessibilité des sites d'emploi ivoiriens depuis GitHub Actions.

Pour chaque source, teste 3 niveaux d'accès (du plus simple au plus robuste) :
  L1  python_default   : httpx avec le User-Agent par défaut (robot "visible")
  L2  browser_headers  : httpx avec des en-têtes de navigateur réalistes
  L3  curl_cffi_chrome : curl_cffi qui imite l'empreinte TLS de Chrome

Puis vérifie : présence des offres dans le HTML (rendu serveur ou JavaScript),
signes de protection anti-bot (Cloudflare…), flux RSS, robots.txt.

Usage : python diagnostic/diag.py --config diagnostic/sources.yaml --out out
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import yaml
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # le diagnostic reste utilisable sans curl_cffi
    cffi_requests = None

DELAY_S = float(__import__("os").environ.get("DIAG_DELAY", 3))  # politesse : pause entre deux requêtes vers un même site
TIMEOUT_S = 20

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-CI,fr;q=0.9,en;q=0.6",
    "Referer": "https://www.google.com/",
}

ANTIBOT_MARKERS = [
    "just a moment",
    "cf-chl",
    "challenge-platform",
    "captcha",
    "attention required",
    "access denied",
    "ddos-guard",
]


@dataclass
class Attempt:
    level: str
    ok: bool = False
    status: int | None = None
    elapsed_s: float | None = None
    bytes: int = 0
    final_url: str | None = None
    server: str | None = None
    cloudflare: bool = False
    antibot_markers: list[str] = field(default_factory=list)
    offer_links: int = 0
    text_len: int = 0
    keyword_hits: int = 0
    error: str | None = None


@dataclass
class SourceReport:
    id: str
    name: str
    url: str
    attempts: list[Attempt] = field(default_factory=list)
    rss_found: list[str] = field(default_factory=list)
    robots_allowed: bool | None = None
    sample_offers: list[str] = field(default_factory=list)
    verdict: str = ""
    recommendation: str = ""


# ---------------------------------------------------------------- requêtes
def fetch(level: str, url: str) -> tuple[int, str, dict, str, float]:
    """Renvoie (status, html, headers, final_url, elapsed)."""
    t0 = time.monotonic()
    if level == "python_default":
        r = httpx.get(url, timeout=TIMEOUT_S, follow_redirects=True)
        return r.status_code, r.text, dict(r.headers), str(r.url), time.monotonic() - t0
    if level == "browser_headers":
        r = httpx.get(url, headers=BROWSER_HEADERS, timeout=TIMEOUT_S, follow_redirects=True)
        return r.status_code, r.text, dict(r.headers), str(r.url), time.monotonic() - t0
    if level == "curl_cffi_chrome":
        if cffi_requests is None:
            raise RuntimeError("curl_cffi non installé")
        r = cffi_requests.get(url, impersonate="chrome", timeout=TIMEOUT_S, allow_redirects=True)
        return r.status_code, r.text, dict(r.headers), str(r.url), time.monotonic() - t0
    raise ValueError(level)


def analyse(html: str, offer_regex: str, keywords: list[str]) -> tuple[int, int, int, list[str], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    low = text.lower() + " " + html[:5000].lower()
    markers = [m for m in ANTIBOT_MARKERS if m in low]
    pattern = re.compile(offer_regex, re.I)
    links = {a["href"] for a in soup.find_all("a", href=True) if pattern.search(a["href"])}
    samples = []
    for a in soup.find_all("a", href=True):
        if pattern.search(a["href"]):
            label = a.get_text(" ", strip=True)
            if label and label not in samples:
                samples.append(label[:90])
        if len(samples) >= 3:
            break
    hits = sum(text.lower().count(k.lower()) for k in keywords)
    return len(links), len(text), hits, markers, samples


def find_rss(base_url: str, html: str | None, candidates: list[str]) -> list[str]:
    found: list[str] = []
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("link", rel=True, href=True):
            t = (link.get("type") or "").lower()
            if "rss" in t or "atom" in t:
                found.append(urljoin(base_url, link["href"]))
    root = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    for path in candidates:
        url = root + path
        try:
            time.sleep(1)
            r = httpx.get(url, headers=BROWSER_HEADERS, timeout=TIMEOUT_S, follow_redirects=True)
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and ("xml" in ctype or r.text.lstrip().startswith("<?xml")):
                found.append(url)
        except Exception:
            pass
    return sorted(set(found))


def robots_allowed(url: str) -> bool | None:
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    try:
        r = httpx.get(root + "/robots.txt", headers=BROWSER_HEADERS, timeout=TIMEOUT_S)
        if r.status_code != 200:
            return None
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(BROWSER_HEADERS["User-Agent"], url)
    except Exception:
        return None


# ---------------------------------------------------------------- verdict
def conclude(rep: SourceReport) -> None:
    ok_levels = [a.level for a in rep.attempts if a.ok and a.offer_links > 0]
    reachable = [a for a in rep.attempts if a.ok]
    if rep.rss_found:
        rss_note = " Flux RSS disponible : à privilégier."
    else:
        rss_note = ""
    if ok_levels:
        lvl = ok_levels[0]
        rep.verdict = f"OK ({lvl})"
        rep.recommendation = {
            "python_default": "Scraping simple httpx + BeautifulSoup.",
            "browser_headers": "httpx + en-têtes navigateur obligatoires.",
            "curl_cffi_chrome": "Utiliser curl_cffi (impersonate='chrome').",
        }[lvl] + rss_note
    elif reachable:
        rep.verdict = "ACCESSIBLE MAIS 0 OFFRE"
        rep.recommendation = (
            "Page reçue sans liens d'offres : rendu JavaScript ou motif d'URL à corriger. "
            "Vérifier le HTML sauvegardé ; sinon Playwright ou API interne du site." + rss_note
        )
    else:
        rep.verdict = "BLOQUÉ depuis GitHub"
        rep.recommendation = (
            "Passer par les alertes email du site (IMAP) ou le relais Google Apps Script." + rss_note
        )


# ---------------------------------------------------------------- main
def run(config_path: Path, out: Path) -> list[SourceReport]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    keywords = cfg.get("keywords", [])
    out.mkdir(parents=True, exist_ok=True)
    (out / "html").mkdir(exist_ok=True)
    reports: list[SourceReport] = []

    for src in cfg["sources"]:
        rep = SourceReport(id=src["id"], name=src["name"], url=src["url"])
        best_html: str | None = None
        for level in ("python_default", "browser_headers", "curl_cffi_chrome"):
            att = Attempt(level=level)
            try:
                status, html, headers, final_url, elapsed = fetch(level, src["url"])
                att.status, att.elapsed_s = status, round(elapsed, 2)
                att.bytes, att.final_url = len(html.encode()), final_url
                att.server = headers.get("server") or headers.get("Server")
                att.cloudflare = any(k.lower().startswith("cf-") for k in headers) or (
                    (att.server or "").lower() == "cloudflare"
                )
                links, tlen, hits, markers, samples = analyse(html, src["offer_link_regex"], keywords)
                att.offer_links, att.text_len, att.keyword_hits = links, tlen, hits
                att.antibot_markers = markers
                att.ok = 200 <= status < 300 and not (markers and links == 0)
                (out / "html" / f"{src['id']}_{level}.html").write_text(html, encoding="utf-8")
                if att.ok and (best_html is None or links > 0):
                    best_html = html
                    if samples and not rep.sample_offers:
                        rep.sample_offers = samples
            except Exception as exc:  # une erreur n'arrête pas le diagnostic
                att.error = f"{type(exc).__name__}: {exc}"[:200]
            rep.attempts.append(att)
            time.sleep(DELAY_S)

        rep.rss_found = find_rss(src["url"], best_html, src.get("rss_candidates", []))
        rep.robots_allowed = robots_allowed(src["url"])
        conclude(rep)
        reports.append(rep)
        print(f"[{rep.id}] {rep.verdict}")

    write_reports(reports, out)
    return reports


def write_reports(reports: list[SourceReport], out: Path) -> None:
    (out / "report.json").write_text(
        json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Diagnostic des sources — exécuté depuis GitHub Actions",
        "",
        "| Source | Verdict | Recommandation | RSS | robots.txt |",
        "|---|---|---|---|---|",
    ]
    for r in reports:
        robots = {True: "autorisé", False: "interdit", None: "n/a"}[r.robots_allowed]
        rss = "<br>".join(r.rss_found) or "—"
        lines.append(f"| {r.name} | **{r.verdict}** | {r.recommendation} | {rss} | {robots} |")
    lines += ["", "## Détail par niveau d'accès", ""]
    for r in reports:
        lines += [
            f"### {r.name}",
            f"URL : {r.url}",
            "",
            "| Niveau | HTTP | Temps (s) | Taille | Liens d'offres | Mots-clés | Cloudflare | Anti-bot | Erreur |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for a in r.attempts:
            lines.append(
                f"| {a.level} | {a.status or '—'} | {a.elapsed_s or '—'} | {a.bytes} | "
                f"{a.offer_links} | {a.keyword_hits} | {'oui' if a.cloudflare else 'non'} | "
                f"{', '.join(a.antibot_markers) or '—'} | {a.error or '—'} |"
            )
        if r.sample_offers:
            lines += ["", "Exemples d'offres détectées : " + " · ".join(r.sample_offers)]
        lines.append("")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("diagnostic/sources.yaml"))
    p.add_argument("--out", type=Path, default=Path("out"))
    args = p.parse_args()
    run(args.config, args.out)
