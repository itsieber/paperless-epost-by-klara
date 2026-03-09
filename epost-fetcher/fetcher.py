#!/usr/bin/env python3
"""
E-Post → Paperless-ngx Fetcher
Holt PDFs von mehreren E-Post Accounts und legt sie in account-spezifische
Consume-Unterordner, damit Paperless sie getrennt verarbeitet.
"""

import os
import time
import logging
import requests
import json
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("epost-fetcher")

# ── Konfiguration ─────────────────────────────────────────────────────────────
EPOST_API_BASE  = "https://api.epost.ch/epost/v2"
CONSUME_DIR     = os.environ.get("CONSUME_DIR", "/consume")
FETCH_INTERVAL  = int(os.environ.get("FETCH_INTERVAL", "900"))
DELETE_AFTER    = os.environ.get("DELETE_AFTER", "true").lower() == "true"
STATE_FILE      = os.environ.get("STATE_FILE", "/data/imported.json")

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

    def list_letters(self) -> list:
        letters = []
        page, size = 0, 50
        while True:
            resp = self.session.get(
                f"{EPOST_API_BASE}/letters",
                params={
                    "letter-folder": "INBOX_FOLDER",
                    "limit":         size,
                    "offset":        page * size,
                },
                timeout=30
            )
            resp.raise_for_status()
            batch = resp.json()
            letters.extend(batch)
            if len(batch) < size:
                break
            page += 1
        return letters

    def download_pdf(self, letter_id: str) -> bytes:
        resp = self.session.get(
            f"{EPOST_API_BASE}/letters/{letter_id}/content",
            headers={"Accept": "application/octet-stream"},
            timeout=60
        )
        resp.raise_for_status()
        return resp.content

    def delete_letter(self, letter_id: str):
        resp = self.session.delete(
            f"{EPOST_API_BASE}/letters/{letter_id}",
            timeout=30
        )
        if resp.status_code >= 400:
            log.warning(f"[{self.account_name}] Löschen fehlgeschlagen für {letter_id}: HTTP {resp.status_code}")


# ── Fetch-Logik ───────────────────────────────────────────────────────────────
def fetch_account(client: EPostClient, consume_dir: Path, imported: set):
    log.info(f"[{client.account_name}] Prüfe Posteingang...")

    try:
        letters = client.list_letters()
    except Exception as e:
        log.error(f"[{client.account_name}] Fehler beim Abrufen der Briefe: {e}")
        return

    new_count = 0
    for letter in letters:
        letter_id = letter.get("id")
        if not letter_id or letter_id in imported:
            continue

        title    = letter.get("letterTitle", letter_id)
        filename = f"{letter_id}.pdf"
        dest     = consume_dir / filename

        log.info(f"[{client.account_name}] Lade herunter: {title} ({letter_id})")

        try:
            pdf_bytes = client.download_pdf(letter_id)
        except Exception as e:
            log.error(f"[{client.account_name}] Download fehlgeschlagen für {letter_id}: {e}")
            continue

        try:
            dest.write_bytes(pdf_bytes)
            log.info(f"[{client.account_name}] Gespeichert → {dest}")
        except Exception as e:
            log.error(f"[{client.account_name}] Speichern fehlgeschlagen für {dest}: {e}")
            continue

        imported.add(letter_id)
        new_count += 1

        if DELETE_AFTER:
            client.delete_letter(letter_id)
            log.info(f"[{client.account_name}] Auf E-Post gelöscht: {letter_id}")

    if new_count == 0:
        log.info(f"[{client.account_name}] Keine neuen Briefe.")
    else:
        log.info(f"[{client.account_name}] {new_count} Brief(e) importiert.")


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

    log.info(f"Starte E-Post Fetcher mit {len(accounts)} Account(s), Intervall: {FETCH_INTERVAL}s")

    while True:
        imported = load_state()

        for account in accounts:
            api_key = account.get("key", "").strip()
            name    = account.get("name", "unbekannt").strip()

            if not api_key:
                log.warning(f"Account '{name}' hat keinen API-Key, überspringe.")
                continue

            consume_dir = Path(CONSUME_DIR) / name
            consume_dir.mkdir(parents=True, exist_ok=True)

            client = EPostClient(api_key=api_key, account_name=name)
            fetch_account(client, consume_dir, imported)

        save_state(imported)
        log.info(f"Nächster Durchlauf in {FETCH_INTERVAL}s ...")
        time.sleep(FETCH_INTERVAL)


if __name__ == "__main__":
    main()
