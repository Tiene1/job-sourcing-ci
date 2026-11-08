"""Un collecteur par source. Chacun renvoie list[Offre] (liste brute, avant scoring)."""

from __future__ import annotations

import email.utils
import os
import re
from datetime import date, timedelta
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from .core import LINKEDIN_JOB_RE, canonical_url, Http, Offre, card_of, clean, extract_email_html

DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")


def trim_to_offer(text: str, titre: str, size: int = 5000) -> str:
    """Coupe le menu du site : garde le texte à partir de la DERNIÈRE mention du titre
    dans le premier tiers de la page (le titre apparaît d'abord dans le fil d'Ariane)."""
    low, t = text.lower(), (titre or "").lower().strip()
    pos = -1
    if t:
        head = low[: max(len(low) // 3, 2000)]
        pos = head.rfind(t)
    return (text[pos:] if pos > 0 else text)[:size]


# ------------------------------------------------------------ Jobivoire.ci
def jobivoire(http: Http, cfg: dict) -> list[Offre]:
    out: dict[str, Offre] = {}
    for p in range(1, cfg.get("pages", 1) + 1):
        url = cfg["url"] + (f"?page={p}" if p > 1 else "")
        soup = http.soup(url)
        for a in soup.find_all("a", href=re.compile(r"/job/[A-Za-z0-9]{9}$")):
            link = urljoin(url, a["href"])
            label = clean(a.get_text(" ").replace("Voir l'offre", ""))
            if link in out:
                if label and not out[link].titre:
                    out[link].titre = label
                continue
            card = clean(card_of(a).get_text(" | "))
            out[link] = Offre(source="jobivoire", url=link, titre=label, description=card)
    return [o for o in out.values() if o.titre]


def jobivoire_detail(http: Http, o: Offre) -> None:
    html = http.get(o.url)
    o.email_contact = o.email_contact or extract_email_html(html)
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        o.titre = clean(h1.get_text(" ")) or o.titre
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.body
    if main:
        o.description = trim_to_offer(clean(main.get_text(" ")), o.titre)


# ------------------------------------------------------------ Educarriere.ci
def educarriere(http: Http, cfg: dict) -> list[Offre]:
    out: dict[str, Offre] = {}
    for p in range(1, cfg.get("pages", 1) + 1):
        url = cfg["url"] if p == 1 else cfg["url"].rstrip("/") + f"/{p}"
        soup = http.soup(url)
        for a in soup.find_all("a", href=re.compile(r"/offre-\d+-")):
            link = urljoin(url, a["href"])
            if link in out:
                continue
            title = clean(a.get_text(" "))
            card = card_of(a)
            text = clean(card.get_text(" | "))
            dates = DATE_RE.findall(text)
            out[link] = Offre(
                source="educarriere", url=link, titre=title, description=text,
                date_limite=dates[-1] if dates else "",
            )
    return [o for o in out.values() if o.titre]


def generic_detail(http: Http, o: Offre) -> None:
    html = http.get(o.url)
    o.email_contact = o.email_contact or extract_email_html(html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    o.description = trim_to_offer(clean(soup.get_text(" ")), o.titre)


# ------------------------------------------------------------ Novojob (RSS)
def novojob(http: Http, cfg: dict) -> list[Offre]:
    feed = feedparser.parse(http.get(cfg["rss"]))
    out = []
    for e in feed.entries:
        summary = clean(BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" "))
        out.append(Offre(
            source="novojob", url=e.get("link", ""), titre=clean(e.get("title", "")),
            description=summary, date_pub=e.get("published", ""),
        ))
    return [o for o in out if o.url and o.titre]


# ------------------------------------------------------------ Alertes email (IMAP)
ALERTE_PARASITE = re.compile(
    r"^votre alerte|^voir (toutes|plus)|^see all|désinscri|unsubscribe|paramètres|settings|"
    r"^g[ée]rer|^modifier l.alerte|^rechercher", re.I)


def _linkedin_split(labels: list[str]) -> tuple[str, str, str]:
    """LinkedIn met dans un lien « Titre » et dans un autre « Titre Entreprise · Lieu (Sur site) ».
    Retourne (titre, entreprise, lieu)."""
    labels = sorted(set(labels), key=len)
    titre = labels[0]
    entreprise = lieu = ""
    for lab in labels[1:]:
        reste = lab[len(titre):].strip() if lab.startswith(titre) else lab
        if "·" in reste:
            entreprise, lieu = (x.strip() for x in reste.split("·", 1))
            lieu = re.sub(r"\s*\((sur site|hybride|à distance|on-site|hybrid|remote)\)\s*$", "", lieu, flags=re.I)
            break
    if "·" in titre and not entreprise:          # un seul lien, tout dans le libellé
        tete, lieu = (x.strip() for x in titre.rsplit("·", 1))
        titre, entreprise = tete, ""
    return titre, entreprise, lieu


def email_alerts(http: Http, cfg: dict) -> list[Offre]:
    user, pwd = os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASSWORD")
    if not (user and pwd):
        print("  [email_alerts] ignoré : secrets GMAIL_USER / GMAIL_APP_PASSWORD absents")
        return []
    from imap_tools import AND, MailBox

    since = date.today() - timedelta(days=cfg.get("since_days", 2))
    groupes: dict[str, dict] = {}     # url canonique → libellés + carte
    with MailBox("imap.gmail.com").login(user, pwd, initial_folder=cfg.get("imap_folder", "INBOX")) as mb:
        for msg in mb.fetch(AND(date_gte=since), mark_seen=False, bulk=True):
            sender = (msg.from_ or "").lower()
            src = next((s for s in cfg["senders"] if s in sender), None)
            if not src or not msg.html:
                continue
            soup = BeautifulSoup(msg.html, "html.parser")
            for a in soup.find_all("a", href=True):
                label, href = clean(a.get_text(" ")), a["href"]
                if len(label) < 8 or not re.search(r"offre|job|emploi|view", href, re.I):
                    continue
                if ALERTE_PARASITE.search(label) or re.search(r"search-results|/jobs/search|/jobs/collections", href, re.I):
                    continue                       # en-têtes d'alerte, liens de recherche : pas des offres
                url = canonical_url(href)
                if "linkedin.com" in href and not LINKEDIN_JOB_RE.search(href):
                    continue                       # liens LinkedIn qui ne pointent pas vers une offre
                g = groupes.setdefault(url, {"src": src, "labels": [], "card": "", "date": msg.date})
                g["labels"].append(label)
                g["card"] = g["card"] or clean(card_of(a).get_text(" | "))

    out = []
    for url, g in groupes.items():
        titre, entreprise, lieu = _linkedin_split(g["labels"]) if "linkedin.com" in url else (min(g["labels"], key=len), "", "")
        out.append(Offre(
            source=f"email:{g['src']}", url=url, titre=titre, entreprise=entreprise, lieu=lieu,
            description=g["card"],
            date_pub=email.utils.format_datetime(g["date"]) if g["date"] else "",
        ))
    return out


COLLECTORS = {
    "jobivoire": (jobivoire, jobivoire_detail),
    "educarriere": (educarriere, generic_detail),
    "novojob": (novojob, generic_detail),
    "email_alerts": (email_alerts, None),   # pas de fiche : Emploi.ci bloque les robots
}
