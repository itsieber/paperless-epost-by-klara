# Klara ePost PDF-Grabber

Automatischer Download aller PDFs aus der Klara ePost-Briefbox (DigitalLetterboxOverview).

## Voraussetzungen

- Python 3.10+
- Klara-Account mit aktivierter ePost (KLARA myLife oder Business)

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Konfiguration

```bash
cp .env.example .env
# .env mit Editor öffnen und Credentials eintragen
```

Inhalt von `.env`:
```
KLARA_USERNAME=deine@email.ch
KLARA_PASSWORD=dein_passwort
KLARA_COMPANY=                 # Optional: Firmenname (Substring), leer = erste Firma
DOWNLOAD_DIR=./downloads       # Zielverzeichnis für PDFs
```

## Verwendung

```bash
.venv/bin/python -m src.main
```

## Login-Flow

Der Grabber führt folgende Schritte automatisch durch:

1. **Keycloak-Login** via `login.klara.ch`
2. **Firmen-Auswahl** (PrimeFaces DataTable, 3 Schritte: contentLoad → rowSelect → selectCompany)
3. **JS-Redirect** von `RedirectToSpecificUrl.xhtml` → KLARA myLife Dashboard
4. **"Digitaler Briefkasten"** Button-Klick auf dem Dashboard → `DigitalLetterboxOverview.xhtml`
5. **Letter-IDs** aus dem HTML extrahieren (Regex, da `letter-id` kein Standard-HTML-Attribut)
6. **PDF-Download** via `https://app.klara.ch/luz/api/epost-storage/downloads/letters/{id}`

## Dateinamen-Format

```
YYYY-MM-DD_Titel.pdf
```

Das Datum wird aus der MongoDB ObjectID des Briefes extrahiert (erste 4 Bytes = Unix-Timestamp).  
Bei Namenskollisionen wird eine Kurz-ID (`_{6_Zeichen_der_LetterID}.pdf`) angehängt.

## Zweiter Lauf (nur neue PDFs)

Beim zweiten Ausführen werden bereits heruntergeladene PDFs dank `.downloaded_ids.json` übersprungen:

```
downloads/
├── .downloaded_ids.json      ← Tracking-Datei (Letter-ID → Dateiname)
├── 2026-03-04_Gescannter Brief.pdf
├── 2026-03-04_Gescannter Brief_b425e3.pdf
└── 2026-03-03_Rechnung Nr._595496.pdf
```

## Firma wählen

Falls du mehrere Firmen/Profile hast, setze `KLARA_COMPANY` auf einen Teil des Firmennamens:

```
KLARA_COMPANY=itSieber AG
```

Verfügbare Profile werden im Log ausgegeben:
```
Firmen gefunden: ['Andreas Michael Sieber', 'itSieber AG', 'Sieber Engineering AG']
```
