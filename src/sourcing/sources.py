"""Un collecteur par source. Chacun renvoie list[Offre] (liste brute, avant scoring)."""

from __future__ import annotations

import email.utils
import os
import re
from datetime import date, timedelta
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from .core import Http, Offre, card_of, clean

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
    soup = http.soup(o.url)
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
    soup = http.soup(o.url)
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
def email_alerts(http: Http, cfg: dict) -> list[Offre]:
    user, pwd = os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASSWORD")
    if not (user and pwd):
        print("  [email_alerts] ignoré : secrets GMAIL_USER / GMAIL_APP_PASSWORD absents")
        return []
    from imap_tools import AND, MailBox

    since = date.today() - timedelta(days=cfg.get("since_days", 2))
    out: dict[str, Offre] = {}
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
                if re.search(r"désinscri|unsubscribe|voir toutes|paramètres|settings", label, re.I):
                    continue
                out.setdefault(href, Offre(
                    source=f"email:{src}", url=href, titre=label,
                    description=clean(card_of(a).get_text(" | ")),
                    date_pub=email.utils.format_datetime(msg.date) if msg.date else "",
                ))
    return list(out.values())


COLLECTORS = {
    "jobivoire": (jobivoire, jobivoire_detail),
    "educarriere": (educarriere, generic_detail),
    "novojob": (novojob, generic_detail),
    "email_alerts": (email_alerts, None),   # pas de fiche : Emploi.ci bloque les robots
}
