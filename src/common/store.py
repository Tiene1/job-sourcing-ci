"""Accès Google (Sheets + Drive) via compte de service. Source unique du schéma de données."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# Schéma de l'onglet Candidatures (partagé avec Apps Script : apps-script/Code.gs)
COLUMNS = [
    "id", "date_detection", "source", "url", "entreprise", "titre", "lieu", "contrat",
    "mots_cles", "score", "email_contact", "date_pub", "date_limite", "statut", "description",
    "adequation", "points_forts", "contenu_cv", "prompt_claude_design", "objet_mail", "lettre",
    "cv_file_id", "date_preparation", "date_envoi", "thread_id", "date_reponse",
    "date_entretien", "resultat", "erreur", "notes",
]
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]
CELL_MAX = 45000  # limite Google Sheets : 50 000 caractères par cellule


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def enabled() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("SHEET_ID"))


def credentials():
    from google.oauth2.service_account import Credentials

    return Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]), scopes=SCOPES
    )


class Store:
    def __init__(self):
        import gspread

        self.gspread = gspread
        self.creds = credentials()
        self.sh = gspread.authorize(self.creds).open_by_key(os.environ["SHEET_ID"])
        self.ws = self._tab("Candidatures", COLUMNS)

    # ---------------------------------------------------------------- onglets
    def _tab(self, name: str, header: list[str]):
        try:
            ws = self.sh.worksheet(name)
        except self.gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(name, rows=1000, cols=max(len(header), 5))
        current = ws.row_values(1)
        if not current:
            ws.update([header], "A1")
        else:  # ajoute les colonnes manquantes sans toucher à l'existant
            missing = [c for c in header if c not in current]
            if missing:
                ws.update([current + missing], "A1")
        return ws

    def header(self) -> list[str]:
        return self.ws.row_values(1)

    # ---------------------------------------------------------------- lecture
    def records(self) -> list[dict]:
        values = self.ws.get_all_values()
        if not values:
            return []
        head = values[0]
        return [dict(zip(head, row), _row=i + 2) for i, row in enumerate(values[1:])]

    def ids(self) -> set[str]:
        head = self.header()
        col = head.index("id") + 1
        return set(self.ws.col_values(col)[1:])

    def params(self) -> dict:
        try:
            rows = self.sh.worksheet("Parametres").get_all_values()
        except self.gspread.WorksheetNotFound:
            return {}
        return {r[0]: r[1] for r in rows[1:] if len(r) >= 2 and r[0]}

    # ---------------------------------------------------------------- écriture
    def append(self, rows: list[dict]) -> None:
        if not rows:
            return
        head = self.header()
        data = [[str(r.get(c, ""))[:CELL_MAX] for c in head] for r in rows]
        self.ws.append_rows(data, value_input_option="RAW")  # une écriture groupée

    def update(self, row: int, fields: dict) -> None:
        from gspread.utils import rowcol_to_a1

        head = self.header()
        batch = [
            {"range": rowcol_to_a1(row, head.index(k) + 1), "values": [[str(v)[:CELL_MAX]]]}
            for k, v in fields.items() if k in head
        ]
        if batch:
            self.ws.batch_update(batch, value_input_option="RAW")

    def log(self, kind: str, message: str) -> None:
        ws = self._tab("Journal", ["date", "type", "message"])
        ws.append_row([now(), kind, message[:2000]], value_input_option="RAW")

    # ---------------------------------------------------------------- cache profil
    def profile_cache(self) -> tuple[object, dict]:
        ws = self._tab("Profil_cache", ["file_id", "nom", "categorie", "modifie", "texte"])
        rows = ws.get_all_values()[1:]
        return ws, {r[0]: {"nom": r[1], "categorie": r[2], "modifie": r[3], "texte": r[4] if len(r) > 4 else ""}
                    for r in rows if r}
