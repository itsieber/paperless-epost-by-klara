"""Konfiguration aus .env-Datei laden."""
import os
from pathlib import Path
from dotenv import load_dotenv

# .env aus dem Projektroot laden
load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    USERNAME: str = os.getenv("KLARA_USERNAME", "")
    PASSWORD: str = os.getenv("KLARA_PASSWORD", "")
    DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
    # Firma-Name oder -Index (0-basiert) für die Auswahl beim Login
    # Leer lassen = erste Firma automatisch wählen
    COMPANY_NAME: str = os.getenv("KLARA_COMPANY", "")
    # Direkter Einstiegs-URL für die ePost-Briefbox
    # Kann aus dem Browser kopiert werden: https://app.klara.ch/luz/pro/luz_epost_business_web/...start.ivp
    # Leer = automatische Suche
    EPOST_START_URL: str = os.getenv("KLARA_EPOST_URL", "")

    # Klara / Keycloak URLs
    KEYCLOAK_AUTH_URL = (
        "https://login.klara.ch/auth/realms/klara/protocol/openid-connect/auth"
    )
    APP_BASE_URL = "https://app.klara.ch"

    # OAuth2 Parameter
    CLIENT_ID = "klara"
    REDIRECT_URI = "https://app.klara.ch/luz/pro/luz_web/148F53807F153C65/oauth_login.ivp"
    SCOPE = "openid email profile"

    @classmethod
    def validate(cls) -> None:
        """Stellt sicher, dass alle Pflicht-Konfigurationen vorhanden sind."""
        missing = []
        if not cls.USERNAME:
            missing.append("KLARA_USERNAME")
        if not cls.PASSWORD:
            missing.append("KLARA_PASSWORD")
        if missing:
            raise ValueError(
                f"Fehlende Umgebungsvariablen: {', '.join(missing)}\n"
                f"Bitte .env-Datei auf Basis von .env.example anlegen."
            )
