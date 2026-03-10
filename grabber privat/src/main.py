"""
Klara PDF-Grabber – Einstiegspunkt.

Verwendung:
    python -m src.main

Voraussetzung: .env-Datei mit KLARA_USERNAME und KLARA_PASSWORD anlegen
               (Vorlage: .env.example)

Optionale .env-Konfiguration:
    KLARA_COMPANY=Andreas Michael Sieber   # Firma-Name (Substring), leer = erste Firma
    DOWNLOAD_DIR=./downloads               # Zielverzeichnis für PDFs
"""

import logging
import sys

from .auth import login
from .config import Config
from .scraper import get_epost_page_url, list_letters
from .downloader import download_all

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("=== Klara PDF-Grabber gestartet ===")

    # Download-Verzeichnis sicherstellen
    Config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Download-Verzeichnis: %s", Config.DOWNLOAD_DIR.resolve())

    try:
        # Schritt 1: Login + Firmen-Auswahl
        session = login()
        logger.info("Session aufgebaut. Hauptseite: %s", session.main_url)

        # Schritt 2: ePost-Briefbox-Seite finden
        epost_url = get_epost_page_url(session)
        logger.info("ePost-Seite: %s", epost_url)

        # Schritt 3: Letter-Liste aus HTML extrahieren
        letters = list_letters(session, epost_url)
        if not letters:
            logger.warning("Keine Briefe in der Briefbox gefunden.")
            return

        logger.info("Briefe in der Briefbox: %d", len(letters))
        for idx, letter in enumerate(letters, 1):
            status = "🗑️ gelöscht" if letter["deleted"] else "📄 aktiv"
            logger.info("  [%d] %s – %s (%s)", idx, letter["id"], letter["title"], status)

        # Schritt 4: PDFs herunterladen
        results = download_all(session, letters, Config.DOWNLOAD_DIR)

        # Zusammenfassung
        logger.info("=== Zusammenfassung ===")
        logger.info("  Heruntergeladen: %d", len(results["downloaded"]))
        logger.info("  Übersprungen:    %d", len(results["skipped"]))
        logger.info("  Fehler:          %d", len(results["errors"]))
        if results["errors"]:
            for err in results["errors"]:
                logger.error("  Fehler bei %s: %s", err["id"], err["error"])

        logger.info("=== Fertig ===")

    except ValueError as e:
        logger.error("Konfiguration/Login-Fehler: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.exception("Unerwarteter Fehler: %s", e)
        sys.exit(2)


if __name__ == "__main__":
    main()
