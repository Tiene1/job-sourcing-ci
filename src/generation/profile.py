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

    if changed or len(fresh_rows) != len(cache):
        ws.clear()
        ws.update([["file_id", "nom", "categorie", "modifie", "texte"]] + fresh_rows, "A1")
    print(f"  [profil] {sum(len(v) for v in out.values())} document(s), {changed} ré-extrait(s)")
    return {k: "\n\n".join(v) for k, v in out.items()}
