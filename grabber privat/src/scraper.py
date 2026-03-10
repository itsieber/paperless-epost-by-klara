"""
Scraper für die Klara ePost-Briefbox (DigitalLetterboxOverview).

Navigation:
1. Nach Login: JS-Redirect von RedirectToSpecificUrl.xhtml → myLife Dashboard
2. Dashboard hat "Digitaler Briefkasten" AJAX-Button → löst Redirect zu ePost aus
3. GET DigitalLetterboxOverview.xhtml → Letter-IDs extrahieren
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from .config import Config

logger = logging.getLogger(__name__)

DOWNLOAD_BASE = f"{Config.APP_BASE_URL}/luz/api/epost-storage/downloads/letters"


def get_epost_page_url(session: requests.Session) -> str:
    """
    Navigiert zur DigitalLetterboxOverview via:
    1. RedirectToSpecificUrl.xhtml → JS-Redirect → Dashboard
    2. Dashboard "Digitaler Briefkasten" Button → AJAX-Redirect → DigitalLetterboxOverview
    """
    main_url = getattr(session, "main_url", "")
    if not main_url:
        raise ValueError("Session hat keine main_url – bitte erst login() aufrufen.")

    # Direkter Treffer
    if "DigitalLetterboxOverview" in main_url:
        return main_url

    # RedirectToSpecificUrl laden → JS-redirectUrl extrahieren
    logger.info("Lade RedirectToSpecificUrl: %s", main_url)
    r_redir = session.get(main_url, allow_redirects=True)
    r_redir.raise_for_status()

    # Direkt auf ePost gelandet?
    if "DigitalLetterboxOverview" in r_redir.url:
        return r_redir.url

    # JS-Redirect-URL suchen
    js_match = re.search(r"var redirectUrl\s*=\s*['\"]([^'\"]+)['\"]", r_redir.text)
    if not js_match:
        raise ValueError("JS-redirectUrl auf RedirectToSpecificUrl.xhtml nicht gefunden.")

    redirect_url = js_match.group(1)
    logger.info("JS-Redirect: %s", redirect_url)

    # Dashboard laden
    r_dash = session.get(redirect_url, allow_redirects=True)
    r_dash.raise_for_status()
    dash_url = r_dash.url
    logger.info("Dashboard geladen: %s", dash_url)

    # Direkt auf ePost gelandet?
    if "DigitalLetterboxOverview" in dash_url:
        return dash_url

    # "Digitaler Briefkasten" AJAX-Button auf dem Dashboard finden
    soup_dash = BeautifulSoup(r_dash.text, "lxml")

    briefkasten_btn = None
    for a in soup_dash.find_all(["a", "button"]):
        text = a.get_text(strip=True).lower()
        onclick = a.get("onclick", "")
        if any(kw in text for kw in ["briefkasten", "epost", "eingang", "letterbox"]):
            briefkasten_btn = a
            break

    if not briefkasten_btn:
        raise ValueError(
            "Kein 'Digitaler Briefkasten'-Button auf dem Dashboard gefunden."
        )

    onclick = briefkasten_btn.get("onclick", "")
    src_match = re.search(r's:"([^"]+)"', onclick)
    form_match = re.search(r'f:"([^"]+)"', onclick)

    if not src_match or not form_match:
        raise ValueError(f"Konnte Source/Form aus Button-onclick nicht lesen: {onclick}")

    src_id = src_match.group(1)
    form_id = form_match.group(1)

    # ViewState und ClientWindow extrahieren
    vs = soup_dash.find("input", {"name": "javax.faces.ViewState"})
    cw = soup_dash.find("input", {"name": "javax.faces.ClientWindow"})
    if not vs or not cw:
        raise ValueError("ViewState/ClientWindow auf Dashboard nicht gefunden.")

    jfwid = cw["value"]
    base = dash_url.split("?")[0]

    logger.info("Klicke 'Digitaler Briefkasten' (source=%s)...", src_id)
    r_click = session.post(
        f"{base}?jfwid={jfwid}",
        headers={
            "Faces-Request": "partial/ajax",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": dash_url,
        },
        data={
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": src_id,
            "javax.faces.partial.execute": "@all",
            src_id: src_id,
            f"{form_id}_SUBMIT": "1",
            "javax.faces.ViewState": vs["value"],
            "javax.faces.ClientWindow": jfwid,
        },
    )
    r_click.raise_for_status()

    redir_match = re.search(r'<redirect url="([^"]+)"', r_click.text)
    if not redir_match:
        raise ValueError("Kein Redirect nach Button-Klick auf 'Digitaler Briefkasten'.")

    epost_url = f"{Config.APP_BASE_URL}{redir_match.group(1)}"
    logger.info("ePost-URL: %s", epost_url)
    return epost_url


def list_letters(session: requests.Session, letterbox_url: str) -> list[dict]:
    """
    Lädt die DigitalLetterboxOverview-Seite und extrahiert alle Letter-Einträge.

    Returns:
        Liste von Dicts mit: id, title, deleted, from_inbox, download_url
    """
    logger.info("Lade ePost-Briefbox...")
    r = session.get(letterbox_url)
    r.raise_for_status()
    return _parse_letters_from_html(r.text)


def _parse_letters_from_html(html: str) -> list[dict]:
    """
    Extrahiert Letter-Metadaten aus dem HTML der DigitalLetterboxOverview.

    Note: BeautifulSoup normalisiert custom HTML-Attribute nicht korrekt,
    daher wird Regex für das Parsen verwendet.
    """
    letters = []
    seen_ids: set[str] = set()

    # Pattern für Letter-Tag: alle Attribute extrahieren
    # Bsp: <div letter-id="69a8..." data-letter-title="..." is-deleted="false" ...>
    pattern = re.compile(
        r'letter-id="([^"]+)"'
        r'(?:[^>]*?data-letter-title="([^"]*)")?'
        r'(?:[^>]*?is-deleted="([^"]*)")?'
        r'(?:[^>]*?is-from-inbox="([^"]*)")?',
        re.DOTALL,
    )

    for match in pattern.finditer(html):
        letter_id = match.group(1)
        if not letter_id or letter_id in seen_ids:
            continue

        seen_ids.add(letter_id)
        title = match.group(2) or "Dokument"
        is_deleted = (match.group(3) or "false").lower() == "true"
        is_inbox = (match.group(4) or "true").lower() == "true"

        letters.append({
            "id": letter_id,
            "title": title,
            "deleted": is_deleted,
            "from_inbox": is_inbox,
            "download_url": f"{DOWNLOAD_BASE}/{letter_id}",
        })

    logger.info(
        "Letters: %d total (aktiv: %d, gelöscht: %d)",
        len(letters),
        sum(1 for l in letters if not l["deleted"]),
        sum(1 for l in letters if l["deleted"]),
    )
    return letters
