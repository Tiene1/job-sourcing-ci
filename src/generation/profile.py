"""Base profil vivante : lit Base_Profil/CV et Base_Profil/LM sur Drive.

Seuls les fichiers nouveaux ou modifiés sont ré-extraits (cache dans l'onglet Profil_cache).
Formats : Google Docs, PDF, DOCX, TXT/MD.
"""

from __future__ import annotations

import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from ..common.store import CELL_MAX, Store

GDOC = "application/vnd.google-apps.document"
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _download(drive, file_id: str) -> bytes:
    buf = io.BytesIO()
    req = drive.files().get_media(fileId=file_id)
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def _extract(drive, f: dict) -> str:
    mime = f["mimeType"]
    if mime == GDOC:
        return drive.files().export(fileId=f["id"], mimeType="text/plain").execute().decode("utf-8", "ignore")
    data = _download(drive, f["id"])
    if mime == PDF:
        from pypdf import PdfReader

        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if mime == DOCX:
        from docx import Document

        return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    if mime.startswith("text/"):
        return data.decode("utf-8", "ignore")
    return ""


def load_portfolio(store: Store, url: str, max_pages: int = 25, refresh_days: int = 7) -> str:
    """Lit le portfolio (accueil, /projects, pages projets et domaines) — mis en cache 7 jours."""
    import re
    from datetime import datetime, timedelta, timezone
    from urllib.parse import urljoin, urlparse

    from bs4 import BeautifulSoup

    from ..sourcing.core import Http, clean

    if not url:
        return ""
    url = url if url.startswith("http") else "https://" + url
    ws, cache = store.profile_cache()
    key = "portfolio:" + urlparse(url).netloc
    c = cache.get(key)
    if c and c["texte"]:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(c["modifie"])
            if age < timedelta(days=refresh_days):
                return c["texte"]
        except ValueError:
            pass
    http, host = Http(delay=1), urlparse(url).netloc
    todo, seen, parts = [url, urljoin(url, "/projects")], set(), []
    while todo and len(seen) < max_pages:
        u = todo.pop(0).split("#")[0].rstrip("/") or url
        if u in seen:
            continue
        seen.add(u)
        try:
            soup = BeautifulSoup(http.get(u), "html.parser")
        except Exception:
            continue
        for a in soup.find_all("a", href=True):
            v = urljoin(u, a["href"]).split("#")[0]
            if urlparse(v).netloc == host and re.search(r"/(projects|projets|domaines|a-propos|about)(/|$)", v):
                todo.append(v)
        for t in soup(["script", "style", "nav", "footer", "svg"]):
            t.decompose()
        txt = clean(soup.get_text(" "))
        if txt:
            parts.append(f"--- {u} ---\n{txt[:6000]}")
    text = "\n\n".join(parts)[:40000]
    rows = [r for r in ws.get_all_values()[1:] if r and r[0] != key]
    rows.append([key, url, "PORTFOLIO", datetime.now(timezone.utc).isoformat(), text])
    ws.clear()
    ws.update([["file_id", "nom", "categorie", "modifie", "texte"]] + rows, "A1")
    print(f"  [profil] portfolio relu : {len(seen)} page(s)")
    return text


def load_profile(store: Store, folders: dict[str, str]) -> dict[str, str]:
    """folders = {"CV": id_dossier, "LM": id_dossier} → {"CV": texte, "LM": texte}."""
    drive = build("drive", "v3", credentials=store.creds, cache_discovery=False)
    ws, cache = store.profile_cache()
    out: dict[str, list[str]] = {k: [] for k in folders}
    fresh_rows, changed = [], 0

    for cat, folder_id in folders.items():
        if not folder_id:
            continue
        files = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id,name,mimeType,modifiedTime)", pageSize=100,
        ).execute().get("files", [])
        for f in sorted(files, key=lambda x: x["modifiedTime"], reverse=True):
            c = cache.get(f["id"])
            if c and c["modifie"] == f["modifiedTime"] and c["texte"]:
                text = c["texte"]
            else:
                try:
                    text = _extract(drive, f).strip()
                except Exception as exc:
                    print(f"  [profil] extraction impossible {f['name']}: {exc}")
                    text = ""
                changed += 1
            if text:
                out[cat].append(f"=== {cat} : {f['name']} (modifié {f['modifiedTime'][:10]}) ===\n{text}")
            fresh_rows.append([f["id"], f["name"], cat, f["modifiedTime"], text[:CELL_MAX]])

    keep = [[k, v["nom"], v["categorie"], v["modifie"], v["texte"]] for k, v in cache.items() if k.startswith("portfolio:")]
    if changed or len(fresh_rows) + len(keep) != len(cache):
        ws.clear()
        ws.update([["file_id", "nom", "categorie", "modifie", "texte"]] + fresh_rows + keep, "A1")
    print(f"  [profil] {sum(len(v) for v in out.values())} document(s), {changed} ré-extrait(s)")
    return {k: "\n\n".join(v) for k, v in out.items()}
