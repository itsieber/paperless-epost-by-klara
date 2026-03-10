"""
PDF-Downloader für die Klara ePost-Briefbox.

Lädt PDFs herunter und speichert sie lokal.
Bereits heruntergeladene Letters werden via .downloaded_ids.json übersprungen.
"""

import datetime
import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote

import requests

logger = logging.getLogger(__name__)

TRACKING_FILE = ".downloaded_ids.json"


def _sanitize_filename(name: str) -> str:
    """Entfernt ungültige Zeichen aus Dateinamen und kürzt auf max. 100 Zeichen."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". _")
    return name[:100] if name else "Dokument"


def _date_from_object_id(object_id: str) -> str:
    """
    Extrahiert das Datum aus einer MongoDB ObjectID (erste 4 Bytes = Unix-Timestamp).
    Gibt das Datum im Format YYYY-MM-DD zurück, oder '' bei Fehler.
    """
    try:
        timestamp = int(object_id[:8], 16)
        return datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def _load_tracking(download_dir: Path) -> dict:
    """Lädt die Tracking-Datei (Letter-ID → Dateiname)."""
    tracking_path = download_dir / TRACKING_FILE
    if tracking_path.exists():
        try:
            with open(tracking_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_tracking(download_dir: Path, tracking: dict) -> None:
    """Speichert die Tracking-Datei."""
    tracking_path = download_dir / TRACKING_FILE
    with open(tracking_path, "w") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)


def download_all(
    session: requests.Session,
    letters: list[dict],
    download_dir: Path,
    skip_deleted: bool = True,
) -> dict:
    """
    Lädt alle PDFs aus der Letter-Liste herunter.

    Args:
        session: Authentifizierte Session
        letters: Liste von Letter-Dicts (aus scraper.list_letters)
        download_dir: Zielverzeichnis für PDFs
        skip_deleted: Gelöschte Briefe überspringen (Standard: True)

    Returns:
        Dict mit 'downloaded', 'skipped', 'errors' Listen
    """
    download_dir.mkdir(parents=True, exist_ok=True)
    tracking = _load_tracking(download_dir)
    results = {"downloaded": [], "skipped": [], "errors": []}

    active = [l for l in letters if not (skip_deleted and l["deleted"])]
    logger.info(
        "Verarbeite %d Letters (%d aktiv, %d gelöscht übersprungen)",
        len(letters),
        len(active),
        len(letters) - len(active),
    )

    for letter in active:
        letter_id = letter["id"]
        title = letter.get("title", "Dokument") or "Dokument"

        # Bereits heruntergeladen? (Letter-ID basiert)
        if letter_id in tracking:
            existing_path = download_dir / tracking[letter_id]
            if existing_path.exists():
                logger.debug("Bereits vorhanden, überspringe: %s", tracking[letter_id])
                results["skipped"].append({"id": letter_id, "path": existing_path})
                continue

        # Dateinamen generieren: YYYY-MM-DD_Titel.pdf
        safe_title = _sanitize_filename(title)
        title_no_ext = re.sub(r'\.pdf$', '', safe_title, flags=re.IGNORECASE)
        date_str = _date_from_object_id(letter_id)

        if date_str:
            base_name = f"{date_str}_{title_no_ext}"
        else:
            base_name = f"{letter_id}_{title_no_ext}"

        filename = f"{base_name}.pdf"
        dest_path = download_dir / filename

        # Kollision mit anderem Letter? Kurz-ID anhängen
        if dest_path.exists():
            short_id = letter_id[-6:]
            filename = f"{base_name}_{short_id}.pdf"
            dest_path = download_dir / filename

        # PDF herunterladen
        try:
            logger.info("Lade herunter: %s ...", filename)
            r = session.get(letter["download_url"], timeout=60, stream=True)
            r.raise_for_status()

            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size_kb = dest_path.stat().st_size // 1024
            logger.info("✓ Gespeichert: %s (%d KB)", dest_path.name, file_size_kb)

            tracking[letter_id] = dest_path.name
            _save_tracking(download_dir, tracking)

            results["downloaded"].append({"id": letter_id, "path": dest_path, "title": title})

        except requests.HTTPError as e:
            logger.error("HTTP-Fehler beim Download von %s: %s", letter_id, e)
            results["errors"].append({"id": letter_id, "error": str(e)})
        except Exception as e:
            logger.error("Fehler beim Download von %s: %s", letter_id, e)
            results["errors"].append({"id": letter_id, "error": str(e)})

    logger.info(
        "Download abgeschlossen: %d geladen, %d übersprungen, %d Fehler",
        len(results["downloaded"]),
        len(results["skipped"]),
        len(results["errors"]),
    )
    return results
