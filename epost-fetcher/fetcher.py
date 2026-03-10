#!/usr/bin/env python3
"""
E-Post → Paperless-ngx Fetcher
Holt PDFs von mehreren E-Post Accounts und legt sie in account-spezifische
Consume-Unterordner, damit Paperless sie getrennt verarbeitet.

Unterstützte Account-Typen:
- business: Klara API-Key (EPOST_ACCOUNTS key + type=business)
- private:  Klara Web-Login (KLARA_USERNAME, KLARA_PASSWORD, KLARA_COMPANY + type=private)

Erweiterte Features:
- Paging für große Letter-Listen (business)
- Alle Subfolders (INBOX_FOLDER, ARCHIVE_FOLDER, etc.)
- Tags und Metadaten als Sidecar-JSON
"""

import os
import time
import logging
import requests
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("epost-fetcher")

VERSION = "2.0.0"  # business + private Klara-Kontos

# ── Konfiguration ─────────────────────────────────────────────────────────────
EPOST_API_BASE  = "https://api.epost.ch/epost/v2"
CONSUME_DIR     = os.environ.get("CONSUME_DIR", "/consume")
FETCH_INTERVAL  = int(os.environ.get("FETCH_INTERVAL", "900"))
DELETE_AFTER    = os.environ.get("DELETE_AFTER", "true").lower() == "true"
STATE_FILE      = os.environ.get("STATE_FILE", "/data/imported.json")
SAVE_METADATA   = os.environ.get("SAVE_METADATA", "true").lower() == "true"

# Welche Folder sollen abgerufen werden? Standardmäßig nur INBOX
# Kann überschrieben werden mit: LETTER_FOLDERS=INBOX_FOLDER,ARCHIVE_FOLDER
LETTER_FOLDERS  = os.environ.get("LETTER_FOLDERS", "INBOX_FOLDER").split(",")

# Accounts als JSON-Array:
# [{"key": "abc123", "name": "firma-a"}, {"key": "xyz789", "name": "firma-b"}]
ACCOUNTS_JSON   = os.environ.get("EPOST_ACCOUNTS", "[]")


# ── State ─────────────────────────────────────────────────────────────────────
def load_state() -> set:
    try:
        with open(STATE_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_state(imported: set):
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(list(imported), f, indent=2)


# ── E-Post API Client ─────────────────────────────────────────────────────────
class EPostClient:
    def __init__(self, api_key: str, account_name: str):
        self.api_key      = api_key
        self.account_name = account_name
        self.session      = requests.Session()
        self.session.headers.update({"X-API-KEY": api_key})

    def list_letters(self, folder: str = "INBOX_FOLDER") -> list:
        """
        Holt alle Letters aus einem bestimmten Folder mit Paging.
        
        API-Dokumentation:
        https://api.klara.ch/docs#/ePost%20Digital%20Letterbox/get_epost_v2_letters
        
        Query-Parameter:
        - letter-folder: INBOX_FOLDER, ARCHIVE_FOLDER, SENT_FOLDER, etc.
        - limit: Anzahl Resultate pro Seite (max 50)
        - offset: Start-Index für Paging
        - sort-by: createdDate, receivedDate, letterTitle, sender
        - sort-order: ASC, DESC
        """
        letters = []
        page, size = 0, 50
        
        while True:
            try:
                resp = self.session.get(
                    f"{EPOST_API_BASE}/letters",
                    params={
                        "letter-folder": folder,
                        "limit":         size,
                        "offset":        page * size,
                        "sort-by":       "receivedDate",
                        "sort-order":    "DESC"
                    },
                    timeout=30
                )
                resp.raise_for_status()
                batch = resp.json()
                
                if not batch:
                    break
                    
                letters.extend(batch)
                log.debug(f"[{self.account_name}] Folder {folder}: Seite {page+1}, {len(batch)} Briefe geladen")
                
                # Wenn weniger als limit zurückkommen, sind wir am Ende
                if len(batch) < size:
                    break
                    
                page += 1
                
            except Exception as e:
                log.error(f"[{self.account_name}] Fehler beim Paging (Seite {page+1}): {e}")
                break
                
        return letters

    def get_letter_details(self, letter_id: str) -> Optional[dict]:
        """
        Holt erweiterte Details zu einem Brief inklusive Tags und allen Metadaten.
        
        API-Dokumentation:
        https://api.klara.ch/docs#/ePost%20Digital%20Letterbox/get_epost_v2_letters__letter_id_
        """
        try:
            resp = self.session.get(
                f"{EPOST_API_BASE}/letters/{letter_id}",
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.error(f"[{self.account_name}] Fehler beim Abrufen von Details für {letter_id}: {e}")
            return None

    def download_pdf(self, letter_id: str) -> bytes:
        """Download PDF-Inhalt eines Briefs."""
        resp = self.session.get(
            f"{EPOST_API_BASE}/letters/{letter_id}/content",
            headers={"Accept": "application/octet-stream"},
            timeout=60
        )
        resp.raise_for_status()
        return resp.content

    def delete_letter(self, letter_id: str):
        """Löscht einen Brief aus dem E-Post Account."""
        resp = self.session.delete(
            f"{EPOST_API_BASE}/letters/{letter_id}",
            timeout=30
        )
        if resp.status_code >= 400:
            log.warning(f"[{self.account_name}] Löschen fehlgeschlagen für {letter_id}: HTTP {resp.status_code}")


# ── Metadata-Extraktion ───────────────────────────────────────────────────────
def extract_metadata(letter: dict) -> dict:
    """
    Extrahiert alle verfügbaren Metadaten aus einem Letter-Objekt.
    
    Verfügbare Felder laut API:
    - id: Brief-ID
    - letterTitle: Titel des Briefs
    - sender: Absender-Name
    - receivedDate: Empfangsdatum (ISO 8601)
    - createdDate: Erstellungsdatum (ISO 8601)
    - letterFolder: Ordner (INBOX_FOLDER, ARCHIVE_FOLDER, etc.)
    - tags: Liste von Tags
    - letterType: Art des Briefs
    - hasAttachments: Boolean
    - pageCount: Anzahl Seiten
    - size: Dateigröße in Bytes
    """
    metadata = {
        "id": letter.get("id"),
        "title": letter.get("letterTitle", "Unbekannt"),
        "sender": letter.get("sender", "Unbekannt"),
        "received_date": letter.get("receivedDate"),
        "created_date": letter.get("createdDate"),
        "folder": letter.get("letterFolder"),
        "tags": letter.get("tags", []),
        "letter_type": letter.get("letterType"),
        "has_attachments": letter.get("hasAttachments", False),
        "page_count": letter.get("pageCount"),
        "size_bytes": letter.get("size"),
    }
    
    # Datum als lesbare Form
    if metadata["received_date"]:
        try:
            dt = datetime.fromisoformat(metadata["received_date"].replace("Z", "+00:00"))
            metadata["received_date_readable"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            pass
    
    return metadata


def save_metadata_sidecar(dest: Path, metadata: dict):
    """
    Speichert Metadaten als JSON-Sidecar-Datei für Paperless-ngx.
    
    Paperless kann diese JSON-Dateien auslesen und automatisch:
    - Tags zuweisen
    - Korrespondenten erkennen
    - Datum setzen
    """
    sidecar_path = dest.with_suffix(".json")
    
    # Paperless-ngx kompatibles Format
    paperless_metadata = {
        "title": metadata.get("title"),
        "correspondent": metadata.get("sender"),
        "created": metadata.get("received_date"),
        "tags": metadata.get("tags", []),
        "document_type": metadata.get("letter_type"),
    }
    
    # Zusätzliche Original-Metadaten
    paperless_metadata["epost_metadata"] = metadata
    
    try:
        sidecar_path.write_text(json.dumps(paperless_metadata, indent=2, ensure_ascii=False))
        log.debug(f"Metadata gespeichert: {sidecar_path}")
    except Exception as e:
        log.error(f"Fehler beim Speichern der Metadata: {e}")


# ── Fetch-Logik ───────────────────────────────────────────────────────────────
def fetch_account(client: EPostClient, consume_dir: Path, imported: set):
    """Holt alle Briefe aus allen konfigurierten Folders für einen Account."""
    
    for folder in LETTER_FOLDERS:
        folder = folder.strip()
        log.info(f"[{client.account_name}] Prüfe Folder: {folder}")

        try:
            letters = client.list_letters(folder=folder)
            log.info(f"[{client.account_name}] {len(letters)} Brief(e) in {folder} gefunden")
        except Exception as e:
            log.error(f"[{client.account_name}] Fehler beim Abrufen von {folder}: {e}")
            continue

        new_count = 0
        for letter in letters:
            letter_id = letter.get("id")
            if not letter_id or letter_id in imported:
                continue

            title = letter.get("letterTitle", letter_id)
            
            # Dateiname: letter_id + sanitized title
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_'))[:50]
            filename = f"{letter_id}_{safe_title}.pdf".replace(" ", "_")
            dest = consume_dir / filename

            log.info(f"[{client.account_name}] Lade herunter: {title} ({letter_id})")

            # Erweiterte Details holen (falls SAVE_METADATA aktiv)
            if SAVE_METADATA:
                detailed_letter = client.get_letter_details(letter_id)
                if detailed_letter:
                    letter = detailed_letter

            # PDF herunterladen
            try:
                pdf_bytes = client.download_pdf(letter_id)
            except Exception as e:
                log.error(f"[{client.account_name}] Download fehlgeschlagen für {letter_id}: {e}")
                continue

            # PDF speichern
            try:
                dest.write_bytes(pdf_bytes)
                log.info(f"[{client.account_name}] Gespeichert → {dest}")
            except Exception as e:
                log.error(f"[{client.account_name}] Speichern fehlgeschlagen für {dest}: {e}")
                continue

            # Metadata als Sidecar speichern
            if SAVE_METADATA:
                metadata = extract_metadata(letter)
                save_metadata_sidecar(dest, metadata)

            imported.add(letter_id)
            new_count += 1

            # Optional: Brief auf E-Post löschen
            if DELETE_AFTER:
                client.delete_letter(letter_id)
                log.info(f"[{client.account_name}] Auf E-Post gelöscht: {letter_id}")

        if new_count == 0:
            log.info(f"[{client.account_name}] Keine neuen Briefe in {folder}.")
        else:
            log.info(f"[{client.account_name}] {new_count} Brief(e) aus {folder} importiert.")


# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    try:
        accounts = json.loads(ACCOUNTS_JSON)
    except json.JSONDecodeError as e:
        log.error(f"EPOST_ACCOUNTS ist kein gültiges JSON: {e}")
        raise SystemExit(1)

    if not accounts:
        log.error("Keine Accounts konfiguriert. Setze EPOST_ACCOUNTS.")
        raise SystemExit(1)

    log.info(f"E-Post Fetcher Version {VERSION}")
    log.info(f"Starte E-Post Fetcher mit {len(accounts)} Account(s)")
    log.info(f"Intervall: {FETCH_INTERVAL}s")
    log.info(f"Folders: {', '.join(LETTER_FOLDERS)}")
    log.info(f"Metadata speichern: {SAVE_METADATA}")
    log.info(f"Löschen nach Import: {DELETE_AFTER}")

    while True:
        imported = load_state()

        for account in accounts:
            name         = account.get("name", "unbekannt").strip()
            account_type = account.get("type", "business").strip().lower()

            consume_dir = Path(CONSUME_DIR) / name
            consume_dir.mkdir(parents=True, exist_ok=True)

            if account_type == "private":
                # ── Privates Klara-Konto (Web-Login) ──────────────────────────
                username     = account.get("KLARA_USERNAME", "").strip()
                password     = account.get("KLARA_PASSWORD", "").strip()
                company_name = account.get("KLARA_COMPANY", "").strip()

                if not username or not password:
                    log.warning(
                        f"Account '{name}' (private) hat kein KLARA_USERNAME / "
                        f"KLARA_PASSWORD, überspringe."
                    )
                    continue

                try:
                    from klara_private import PrivateEPostClient
                except ImportError as e:
                    log.error(
                        f"klara_private.py nicht gefunden – Private-Kontos "
                        f"können nicht genutzt werden: {e}"
                    )
                    continue

                client = PrivateEPostClient(
                    username=username,
                    password=password,
                    company_name=company_name,
                    account_name=name,
                )
                log.info(f"[{name}] Privates Konto (Klara Web-Login)")

            else:
                # ── Geschäftliches Klara-Konto (API-Key) ──────────────────────
                api_key = account.get("key", "").strip()

                if not api_key:
                    log.warning(f"Account '{name}' (business) hat keinen API-Key, überspringe.")
                    continue

                client = EPostClient(api_key=api_key, account_name=name)
                log.info(f"[{name}] Geschäftliches Konto (API-Key)")

            fetch_account(client, consume_dir, imported)

        save_state(imported)
        log.info(f"Nächster Durchlauf in {FETCH_INTERVAL}s ...")
        time.sleep(FETCH_INTERVAL)


if __name__ == "__main__":
    main()
