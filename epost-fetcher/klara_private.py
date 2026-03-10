"""
Klara Private E-Post Client

Authentifiziert sich per Benutzername/Passwort über die Klara-Weboberfläche
und lädt Briefe aus der privaten ePost-Briefbox herunter.

Adaptiert aus: grabber privat/src/ (auth.py, scraper.py, downloader.py)
"""

import logging
import re
import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
logger = logging.getLogger("epost-fetcher.private")

# ── Klara / Keycloak URLs ──────────────────────────────────────────────────────
KEYCLOAK_AUTH_URL = (
    "https://login.klara.ch/auth/realms/klara/protocol/openid-connect/auth"
)
APP_BASE_URL  = "https://app.klara.ch"
CLIENT_ID     = "klara"
REDIRECT_URI  = "https://app.klara.ch/luz/pro/luz_web/148F53807F153C65/oauth_login.ivp"
SCOPE         = "openid email profile"
DOWNLOAD_BASE = f"{APP_BASE_URL}/luz/api/epost-storage/downloads/letters"


def _build_oidc_url() -> str:
    from urllib.parse import urlencode
    params = {
        "client_id":     CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPE,
    }
    return f"{KEYCLOAK_AUTH_URL}?{urlencode(params)}"


def _get_vs_cw(xml_or_html: str, current_vs: str, current_cw: str) -> tuple[str, str]:
    m1 = re.search(
        r"javax\.faces\.ViewState[^\"]*\"><!\[CDATA\[(.*?)\]\]>", xml_or_html
    )
    m2 = re.search(
        r"javax\.faces\.ClientWindow[^\"]*\"><!\[CDATA\[(.*?)\]\]>", xml_or_html
    )
    return (m1.group(1) if m1 else current_vs), (m2.group(1) if m2 else current_cw)


def _ajax_headers(referer: str) -> dict:
    return {
        "Faces-Request":     "partial/ajax",
        "X-Requested-With":  "XMLHttpRequest",
        "Content-Type":      "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer":           referer,
    }


# ── Login ──────────────────────────────────────────────────────────────────────

def _klara_login(username: str, password: str, company_name: str) -> requests.Session:
    """
    Vollständiger Klara-Login mit Firmen-Auswahl.
    Gibt eine authentifizierte Session zurück (mit Attribut `main_url`).
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
    })

    # Schritt 1+2: Keycloak-Login
    logger.info("Lade Keycloak-Loginseite...")
    r1 = session.get(_build_oidc_url(), allow_redirects=True)
    r1.raise_for_status()

    soup = BeautifulSoup(r1.text, "lxml")
    form = soup.find("form", id="loginForm")
    if not form:
        raise ValueError("loginForm nicht gefunden.")
    action_url = form.get("action")
    if not action_url:
        raise ValueError("Form-Action-URL nicht gefunden.")

    logger.info("Sende Login-Credentials...")
    r2 = session.post(
        action_url,
        data={"username": username, "password": password, "login": ""},
        allow_redirects=True,
    )
    r2.raise_for_status()

    if "app.klara.ch" not in r2.url and "login.klara.ch" in r2.url:
        err_soup = BeautifulSoup(r2.text, "lxml")
        err = err_soup.find(class_=re.compile(r"alert|error|kc-feedback"))
        raise ValueError(
            f"Login fehlgeschlagen: {err.get_text(strip=True) if err else 'unbekannt'}"
        )

    company_url = r2.url
    logger.info("Keycloak-Login erfolgreich. Landing: %s", company_url)

    # Schritt 3: UserCompany-Seite
    r3 = session.get(company_url)
    r3.raise_for_status()
    page_soup = BeautifulSoup(r3.text, "lxml")

    vs_input = page_soup.find("input", {"name": "javax.faces.ViewState"})
    cw_input = page_soup.find("input", {"name": "javax.faces.ClientWindow"})
    if not vs_input or not cw_input:
        raise ValueError("ViewState/ClientWindow nicht auf UserCompany-Seite gefunden.")

    vs    = vs_input["value"]
    jfwid = cw_input["value"]
    base_url = company_url.split("?")[0]

    # Schritt 4: Firmen-Liste laden
    logger.info("Lade Firmen-Liste...")
    r_load = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax":           "true",
            "javax.faces.source":                 "j_id_26:selectCompany",
            "javax.faces.partial.execute":        "j_id_26:selectCompany",
            "javax.faces.partial.render":         "j_id_26:selectCompany",
            "j_id_26:selectCompany":              "j_id_26:selectCompany",
            "j_id_26:selectCompany_contentLoad":  "true",
            "j_id_p:j_id_q:formHandleTimeout_SUBMIT": "1",
            "javax.faces.ViewState":              vs,
            "javax.faces.ClientWindow":           jfwid,
        },
    )
    r_load.raise_for_status()
    vs, jfwid = _get_vs_cw(r_load.text, vs, jfwid)

    companies = _parse_companies(r_load.text)
    if not companies:
        raise ValueError("Keine Firmen in der Liste gefunden.")
    logger.info("Firmen gefunden: %s", [c["name"] for c in companies])

    target = _select_company(companies, company_name)
    logger.info("Wähle Firma: %s (%s)", target["name"], target["rk"])

    # Schritt 5: rowSelect
    r_row = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax":   "true",
            "javax.faces.source":         "j_id_26:selectCompanyFrm:listtenants",
            "javax.faces.partial.execute": "j_id_26:selectCompanyFrm:listtenants",
            "javax.faces.behavior.event": "rowSelect",
            "javax.faces.partial.event":  "rowSelect",
            "j_id_26:selectCompanyFrm:listtenants_instantSelectedRowKey": target["rk"],
            "j_id_26:selectCompanyFrm:listtenants_selection":             target["rk"],
            "j_id_26:selectCompanyFrm:listtenants_scrollState":           "0,0",
            "j_id_26:selectCompanyFrm_SUBMIT":                            "1",
            "javax.faces.ViewState":      vs,
            "javax.faces.ClientWindow":   jfwid,
        },
    )
    r_row.raise_for_status()
    vs, jfwid = _get_vs_cw(r_row.text, vs, jfwid)

    # Schritt 6: selectCompany bestätigen
    r_sc = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax":   "true",
            "javax.faces.source":         "j_id_26:j_id_27:j_id_28",
            "javax.faces.partial.execute": "@all",
            "j_id_26:j_id_27:j_id_28":   "j_id_26:j_id_27:j_id_28",
            "j_id_26:j_id_27_SUBMIT":     "1",
            "javax.faces.ViewState":      vs,
            "javax.faces.ClientWindow":   jfwid,
        },
    )
    r_sc.raise_for_status()
    vs, jfwid = _get_vs_cw(r_sc.text, vs, jfwid)

    # Schritt 7: redirectMainPage
    r_rm = session.post(
        f"{base_url}?jfwid={jfwid}",
        headers=_ajax_headers(company_url),
        data={
            "javax.faces.partial.ajax":   "true",
            "javax.faces.source":         "j_id_3w:j_id_3x",
            "javax.faces.partial.execute": "@all",
            "j_id_3w:j_id_3x":           "j_id_3w:j_id_3x",
            "j_id_3w_SUBMIT":             "1",
            "javax.faces.ViewState":      vs,
            "javax.faces.ClientWindow":   jfwid,
        },
    )
    r_rm.raise_for_status()

    redir_match = re.search(r'<redirect url="([^"]+)"', r_rm.text)
    if not redir_match:
        raise ValueError("Kein Redirect nach redirectMainPage – Firmen-Auswahl fehlgeschlagen.")

    # Schritt 8: Hauptseite laden
    main_url = f"{APP_BASE_URL}{redir_match.group(1)}"
    r_main = session.get(main_url, allow_redirects=True)
    r_main.raise_for_status()

    session.main_url = r_main.url
    logger.info("Login + Firmen-Auswahl erfolgreich! Hauptseite: %s", session.main_url)
    return session


def _parse_companies(xml_text: str) -> list[dict]:
    soup = BeautifulSoup(xml_text, "lxml")
    companies = []
    for row in soup.find_all(attrs={"data-rk": True}):
        name_el = row.find(class_="company-name")
        type_el = row.find(class_="company-type")
        companies.append({
            "ri":   row.get("data-ri"),
            "rk":   row.get("data-rk"),
            "name": name_el.get_text(strip=True) if name_el else "",
            "type": type_el.get_text(strip=True) if type_el else "",
        })
    return companies


def _select_company(companies: list[dict], company_name: str) -> dict:
    if not company_name:
        return companies[0]
    target = company_name.lower()
    for c in companies:
        if target in c["name"].lower():
            return c
    raise ValueError(
        f"Firma '{company_name}' nicht gefunden. Verfügbar: {[c['name'] for c in companies]}"
    )


# ── ePost-Seite navigieren ─────────────────────────────────────────────────────

def _get_epost_page_url(session: requests.Session) -> str:
    """Navigiert zur DigitalLetterboxOverview."""
    main_url = getattr(session, "main_url", "")
    if not main_url:
        raise ValueError("Session hat keine main_url.")

    if "DigitalLetterboxOverview" in main_url:
        return main_url

    r_redir = session.get(main_url, allow_redirects=True)
    r_redir.raise_for_status()

    if "DigitalLetterboxOverview" in r_redir.url:
        return r_redir.url

    js_match = re.search(r"var redirectUrl\s*=\s*['\"]([^'\"]+)['\"]", r_redir.text)
    if not js_match:
        raise ValueError("JS-redirectUrl auf RedirectToSpecificUrl.xhtml nicht gefunden.")

    redirect_url = js_match.group(1)
    logger.info("JS-Redirect: %s", redirect_url)

    r_dash = session.get(redirect_url, allow_redirects=True)
    r_dash.raise_for_status()
    dash_url = r_dash.url

    if "DigitalLetterboxOverview" in dash_url:
        return dash_url

    soup_dash = BeautifulSoup(r_dash.text, "lxml")
    briefkasten_btn = None
    for a in soup_dash.find_all(["a", "button"]):
        text = a.get_text(strip=True).lower()
        if any(kw in text for kw in ["briefkasten", "epost", "eingang", "letterbox"]):
            briefkasten_btn = a
            break

    if not briefkasten_btn:
        raise ValueError("Kein 'Digitaler Briefkasten'-Button auf dem Dashboard gefunden.")

    onclick = briefkasten_btn.get("onclick", "")
    src_match  = re.search(r's:"([^"]+)"', onclick)
    form_match = re.search(r'f:"([^"]+)"', onclick)

    if not src_match or not form_match:
        raise ValueError(f"Konnte Source/Form aus Button-onclick nicht lesen: {onclick}")

    src_id  = src_match.group(1)
    form_id = form_match.group(1)

    vs = soup_dash.find("input", {"name": "javax.faces.ViewState"})
    cw = soup_dash.find("input", {"name": "javax.faces.ClientWindow"})
    if not vs or not cw:
        raise ValueError("ViewState/ClientWindow auf Dashboard nicht gefunden.")

    jfwid = cw["value"]
    base  = dash_url.split("?")[0]

    r_click = session.post(
        f"{base}?jfwid={jfwid}",
        headers={
            "Faces-Request":    "partial/ajax",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer":          dash_url,
        },
        data={
            "javax.faces.partial.ajax":   "true",
            "javax.faces.source":         src_id,
            "javax.faces.partial.execute": "@all",
            src_id:                       src_id,
            f"{form_id}_SUBMIT":          "1",
            "javax.faces.ViewState":      vs["value"],
            "javax.faces.ClientWindow":   jfwid,
        },
    )
    r_click.raise_for_status()

    redir_match = re.search(r'<redirect url="([^"]+)"', r_click.text)
    if not redir_match:
        raise ValueError("Kein Redirect nach Button-Klick auf 'Digitaler Briefkasten'.")

    epost_url = f"{APP_BASE_URL}{redir_match.group(1)}"
    logger.info("ePost-URL: %s", epost_url)
    return epost_url


def _list_letters_from_html(html: str) -> list[dict]:
    """Extrahiert Letter-Metadaten aus der DigitalLetterboxOverview."""
    letters = []
    seen_ids: set[str] = set()

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
        title      = match.group(2) or "Dokument"
        is_deleted = (match.group(3) or "false").lower() == "true"

        letters.append({
            "id":           letter_id,
            "letterTitle":  title,
            "deleted":      is_deleted,
            "download_url": f"{DOWNLOAD_BASE}/{letter_id}",
        })

    return letters


# ── PrivateEPostClient ─────────────────────────────────────────────────────────

class PrivateEPostClient:
    """
    Client für private Klara ePost-Kontos.
    Authentifiziert sich per Benutzername/Passwort über die Klara-Weboberfläche.
    Kompatibles Interface zu EPostClient in fetcher.py.
    """

    def __init__(self, username: str, password: str, company_name: str, account_name: str):
        self.username     = username
        self.password     = password
        self.company_name = company_name
        self.account_name = account_name
        self._session: requests.Session | None = None

    def _ensure_session(self):
        if self._session is None:
            logger.info("[%s] Starte Private Klara-Login...", self.account_name)
            self._session = _klara_login(self.username, self.password, self.company_name)

    def list_letters(self, folder: str = "INBOX_FOLDER") -> list[dict]:
        """
        Lädt die Briefbox und gibt alle aktiven Briefe zurück.
        (folder-Parameter wird ignoriert – Private-Interface zeigt alle Briefe)
        """
        self._ensure_session()
        try:
            epost_url = _get_epost_page_url(self._session)
            r = self._session.get(epost_url, timeout=30)
            r.raise_for_status()
            letters = _list_letters_from_html(r.text)
            # Nur nicht-gelöschte zurückgeben
            active = [l for l in letters if not l["deleted"]]
            logger.info(
                "[%s] %d Brief(e) gefunden (%d gelöscht übersprungen)",
                self.account_name, len(active), len(letters) - len(active),
            )
            return active
        except Exception:
            # Session zurücksetzen bei Fehler → nächster Versuch löst Re-Login aus
            self._session = None
            raise

    def download_pdf(self, letter_id: str) -> bytes:
        """Lädt den PDF-Inhalt eines Briefs herunter."""
        self._ensure_session()
        url = f"{DOWNLOAD_BASE}/{letter_id}"
        resp = self._session.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content

    def delete_letter(self, letter_id: str):
        """Nicht unterstützt für Private-Kontos – wird still ignoriert."""
        logger.debug(
            "[%s] delete_letter ignoriert für Private-Konto (letter_id=%s)",
            self.account_name, letter_id,
        )
