"""
Keycloak-basierter Login + Firmen-Auswahl für die Klara-Plattform.

Kompletter Flow:
1. GET Keycloak-Loginseite → Form-Action-URL extrahieren
2. POST Credentials → Session-Cookies + Redirect zu UserCompany.xhtml
3. GET UserCompany.xhtml → ViewState extrahieren
4. AJAX contentLoad → Firmen-Liste laden
5. AJAX rowSelect → Firma serverseitig markieren
6. AJAX selectCompany (j_id_26:j_id_27:j_id_28) → Auswahl bestätigen
7. AJAX redirectMainPage (j_id_3w:j_id_3x) → Redirect-URL erhalten
8. GET RedirectToSpecificUrl.xhtml → eingeloggte Hauptseite
"""

import logging
import re

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

from .config import Config

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
logger = logging.getLogger(__name__)

# ── Keycloak Login-Seite ───────────────────────────────────────────────────────

def _build_oidc_url() -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": Config.CLIENT_ID,
        "response_type": "code",
        "redirect_uri": Config.REDIRECT_URI,
        "scope": Config.SCOPE,
    }
    return f"{Config.KEYCLOAK_AUTH_URL}?{urlencode(params)}"


def _get_vs_cw(xml_or_html: str, current_vs: str, current_cw: str) -> tuple[str, str]:
    """Extrahiert ViewState und ClientWindow aus einem AJAX-Response-XML."""
    m1 = re.search(
        r"javax\.faces\.ViewState[^\"]*\"><!\[CDATA\[(.*?)\]\]>", xml_or_html
    )
    m2 = re.search(
        r"javax\.faces\.ClientWindow[^\"]*\"><!\[CDATA\[(.*?)\]\]>", xml_or_html
    )
    return (m1.group(1) if m1 else current_vs), (m2.group(1) if m2 else current_cw)


def _ajax_headers(referer: str) -> dict:
    return {
        "Faces-Request": "partial/ajax",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": referer,
    }


# ── Haupt-Login ───────────────────────────────────────────────────────────────

def login() -> requests.Session:
    """
    Führt den vollständigen Klara-Login mit Firmen-Auswahl durch.

    Returns:
        requests.Session: Authentifizierte Session, bereit für API-Calls.
        Session hat Attribut `main_url` (URL der eingeloggten Hauptseite).

    Raises:
        ValueError: Bei fehlenden Credentials oder fehlgeschlagenem Login.
        requests.RequestException: Bei Netzwerkfehlern.
    """
    Config.validate()

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
    })

    # ── Schritt 1+2: Keycloak-Login ───────────────────────────────────────────
    logger.info("Lade Keycloak-Loginseite...")
    r1 = session.get(_build_oidc_url(), allow_redirects=True)
    r1.raise_for_status()

    soup = BeautifulSoup(r1.text, "lxml")
    form = soup.find("form", id="loginForm")
    if not form:
        raise ValueError("loginForm nicht auf der Keycloak-Seite gefunden.")

    action_url = form.get("action")
    if not action_url:
        raise ValueError("Form-Action-URL nicht gefunden.")

    logger.info("Sende Login-Credentials...")
    r2 = session.post(
        action_url,
        data={"username": Config.USERNAME, "password": Config.PASSWORD, "login": ""},
        allow_redirects=True,
    )
    r2.raise_for_status()

    if "app.klara.ch" not in r2.url and "login.klara.ch" in r2.url:
        err_soup = BeautifulSoup(r2.text, "lxml")
        err = err_soup.find(class_=re.compile(r"alert|error|kc-feedback"))
        raise ValueError(f"Login fehlgeschlagen: {err.get_text(strip=True) if err else 'unbekannt'}")

    company_url = r2.url
    logger.info("Keycloak-Login erfolgreich. Landing: %s", company_url)

    # ── Schritt 3: UserCompany-Seite laden ───────────────────────────────────
    r3 = session.get(company_url)
    r3.raise_for_status()
    page_soup = BeautifulSoup(r3.text, "lxml")

    vs_input = page_soup.find("input", {"name": "javax.faces.ViewState"})
    cw_input = page_soup.find("input", {"name": "javax.faces.ClientWindow"})
    if not vs_input or not cw_input:
        raise ValueError("ViewState/ClientWindow nicht auf UserCompany-Seite gefunden.")

    vs = vs_input["value"]
    jfwid = cw_input["value"]
    base_url = company_url.split("?")[0]

    # ── Schritt 4: Firmen-Liste laden ─────────────────────────────────────────
    logger.info("Lade Firmen-Liste...")
    r_load = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "j_id_26:selectCompany",
            "javax.faces.partial.execute": "j_id_26:selectCompany",
            "javax.faces.partial.render": "j_id_26:selectCompany",
            "j_id_26:selectCompany": "j_id_26:selectCompany",
            "j_id_26:selectCompany_contentLoad": "true",
            "j_id_p:j_id_q:formHandleTimeout_SUBMIT": "1",
            "javax.faces.ViewState": vs,
            "javax.faces.ClientWindow": jfwid,
        },
    )
    r_load.raise_for_status()
    vs, jfwid = _get_vs_cw(r_load.text, vs, jfwid)

    companies = _parse_companies(r_load.text)
    if not companies:
        raise ValueError("Keine Firmen in der Liste gefunden.")
    logger.info("Firmen gefunden: %s", [c["name"] for c in companies])

    target = _select_company(companies)
    logger.info("Wähle Firma: %s (%s)", target["name"], target["rk"])

    # ── Schritt 5: rowSelect ──────────────────────────────────────────────────
    r_row = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "j_id_26:selectCompanyFrm:listtenants",
            "javax.faces.partial.execute": "j_id_26:selectCompanyFrm:listtenants",
            "javax.faces.behavior.event": "rowSelect",
            "javax.faces.partial.event": "rowSelect",
            "j_id_26:selectCompanyFrm:listtenants_instantSelectedRowKey": target["rk"],
            "j_id_26:selectCompanyFrm:listtenants_selection": target["rk"],
            "j_id_26:selectCompanyFrm:listtenants_scrollState": "0,0",
            "j_id_26:selectCompanyFrm_SUBMIT": "1",
            "javax.faces.ViewState": vs,
            "javax.faces.ClientWindow": jfwid,
        },
    )
    r_row.raise_for_status()
    vs, jfwid = _get_vs_cw(r_row.text, vs, jfwid)

    # ── Schritt 6: selectCompany bestätigen ───────────────────────────────────
    r_sc = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "j_id_26:j_id_27:j_id_28",
            "javax.faces.partial.execute": "@all",
            "j_id_26:j_id_27:j_id_28": "j_id_26:j_id_27:j_id_28",
            "j_id_26:j_id_27_SUBMIT": "1",
            "javax.faces.ViewState": vs,
            "javax.faces.ClientWindow": jfwid,
        },
    )
    r_sc.raise_for_status()
    vs, jfwid = _get_vs_cw(r_sc.text, vs, jfwid)

    # ── Schritt 7: redirectMainPage ───────────────────────────────────────────
    r_rm = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "j_id_3w:j_id_3x",
            "javax.faces.partial.execute": "@all",
            "j_id_3w:j_id_3x": "j_id_3w:j_id_3x",
            "j_id_3w_SUBMIT": "1",
            "javax.faces.ViewState": vs,
            "javax.faces.ClientWindow": jfwid,
        },
    )
    r_rm.raise_for_status()

    redir_match = re.search(r'<redirect url="([^"]+)"', r_rm.text)
    if not redir_match:
        raise ValueError("Kein Redirect nach redirectMainPage – Firmen-Auswahl fehlgeschlagen.")

    redirect_path = redir_match.group(1)

    # ── Schritt 8: Hauptseite laden ───────────────────────────────────────────
    main_url = f"{Config.APP_BASE_URL}{redirect_path}"
    r_main = session.get(main_url, allow_redirects=True)
    r_main.raise_for_status()

    session.main_url = r_main.url
    logger.info("Login + Firmen-Auswahl erfolgreich! Hauptseite: %s", session.main_url)
    return session


def _parse_companies(xml_text: str) -> list[dict]:
    """Extrahiert Firmen-Daten aus dem AJAX-Response."""
    soup = BeautifulSoup(xml_text, "lxml")
    companies = []
    for row in soup.find_all(attrs={"data-rk": True}):
        name_el = row.find(class_="company-name")
        type_el = row.find(class_="company-type")
        companies.append({
            "ri": row.get("data-ri"),
            "rk": row.get("data-rk"),
            "name": name_el.get_text(strip=True) if name_el else "",
            "type": type_el.get_text(strip=True) if type_el else "",
        })
    return companies


def _select_company(companies: list[dict]) -> dict:
    """
    Wählt die Ziel-Firma aus der Liste.
    Konfiguration: KLARA_COMPANY (Name-Substring oder leer für erste Firma).
    """
    if not Config.COMPANY_NAME:
        return companies[0]

    target_name = Config.COMPANY_NAME.lower()
    for company in companies:
        if target_name in company["name"].lower():
            return company

    raise ValueError(
        f"Firma '{Config.COMPANY_NAME}' nicht gefunden. "
        f"Verfügbar: {[c['name'] for c in companies]}"
    )
