# E-Post Fetcher - Erweiterte Features

## Übersicht der implementierten Features

Der E-Post Fetcher wurde erweitert um alle Features der Klara E-Post API zu nutzen.

## 1. Paging für große Letter-Listen

Der Fetcher durchläuft automatisch alle Seiten bei der Abfrage von Briefen:

```python
# Holt alle Briefe mit automatischem Paging
# - limit: 50 Briefe pro Request (API-Maximum)
# - offset: Automatische Berechnung für jede Seite
# - Stoppt, wenn weniger als limit Briefe zurückkommen
```

**Vorteil:** Auch bei hunderten Briefen werden alle abgerufen.

## 2. Alle Subfolders unterstützt

Standardmäßig wird nur der `INBOX_FOLDER` abgerufen. Du kannst aber mehrere Folders konfigurieren:

```bash
# In docker-compose.yml oder .env
LETTER_FOLDERS=INBOX_FOLDER,ARCHIVE_FOLDER
```

**Verfügbare Folders:**
- `INBOX_FOLDER` - Posteingang
- `ARCHIVE_FOLDER` - Archiv
- `SENT_FOLDER` - Gesendete Briefe
- Weitere je nach API-Version

## 3. Tags und Metadaten

Alle von der E-Post API gelieferten Metadaten werden erfasst:

### Extrahierte Felder:

| Feld | Beschreibung |
|------|--------------|
| `id` | Eindeutige Brief-ID |
| `letterTitle` | Titel des Briefs |
| `sender` | Absender-Name |
| `receivedDate` | Empfangsdatum (ISO 8601) |
| `createdDate` | Erstellungsdatum |
| `letterFolder` | Ordner (INBOX, ARCHIVE, etc.) |
| `tags` | Liste von Tags |
| `letterType` | Art des Briefs |
| `hasAttachments` | Hat Anhänge (Boolean) |
| `pageCount` | Anzahl Seiten |
| `size` | Dateigröße in Bytes |

### Metadata-Sidecar-Dateien

Für jeden Brief wird eine JSON-Datei erstellt (z.B. `brief123.pdf` → `brief123.json`):

```json
{
  "title": "Rechnung vom 2024-01-15",
  "correspondent": "Firma XY AG",
  "created": "2024-01-15T10:30:00Z",
  "tags": ["rechnung", "wichtig"],
  "document_type": "invoice",
  "epost_metadata": {
    "id": "letter-uuid-123",
    "page_count": 3,
    "size_bytes": 245678,
    "has_attachments": false,
    "folder": "INBOX_FOLDER"
  }
}
```

**Paperless-ngx Integration:**
Paperless kann diese JSON-Dateien automatisch einlesen und:
- Tags zuweisen
- Korrespondenten erkennen
- Datum setzen
- Dokumenttyp zuordnen

## 4. Erweiterte Details per Letter-ID

Für jeden Brief werden zusätzlich die erweiterten Details via `/letters/{letter_id}` Endpoint abgerufen:

```python
# Holt alle verfügbaren Metadaten für einen Brief
detailed_letter = client.get_letter_details(letter_id)
```

Dies stellt sicher, dass auch Tags und weitere Felder erfasst werden, die in der Listen-Ansicht fehlen könnten.

## 5. Konfigurierbare Optionen

### Umgebungsvariablen

```bash
# Metadata als JSON-Sidecar speichern
SAVE_METADATA=true

# Welche Folders abgerufen werden sollen
LETTER_FOLDERS=INBOX_FOLDER,ARCHIVE_FOLDER

# Briefe nach Import löschen
DELETE_AFTER=true

# Abruf-Intervall in Sekunden
FETCH_INTERVAL=900

# Consume-Verzeichnis
CONSUME_DIR=/consume

# State-File für importierte Brief-IDs
STATE_FILE=/data/imported.json
```

### Beispiel docker-compose.yml

```yaml
epost-fetcher:
  image: ghcr.io/itsieber/paperless-epost-by-klara:latest
  container_name: epost-fetcher
  restart: always
  volumes:
    - /opt/paperless/consume:/consume
    - epost-state:/data
  environment:
    - CONSUME_DIR=/consume
    - FETCH_INTERVAL=900
    - DELETE_AFTER=true
    - SAVE_METADATA=true
    - LETTER_FOLDERS=INBOX_FOLDER,ARCHIVE_FOLDER
    - EPOST_ACCOUNTS=[{"key":"abc123","name":"firma-a"},{"key":"xyz789","name":"firma-b"}]
  networks:
    - internal
```

## 6. Dateinamen-Struktur

Briefe werden mit sprechendem Dateinamen gespeichert:

```
{letter-id}_{sanitized-title}.pdf
```

Beispiel:
```
letter-123456_Rechnung_vom_2024-01-15.pdf
letter-123456_Rechnung_vom_2024-01-15.json
```

## 7. Multi-Account-Unterstützung

Jeder Account bekommt einen eigenen Unterordner:

```
/consume/
  ├── firma-a/
  │   ├── letter-123_Dokument1.pdf
  │   └── letter-123_Dokument1.json
  └── firma-b/
      ├── letter-456_Dokument2.pdf
      └── letter-456_Dokument2.json
```

## API-Referenz

Vollständige API-Dokumentation:
https://api.klara.ch/docs#/ePost%20Digital%20Letterbox/get_epost_v2_letters

## Logging

Der Fetcher loggt ausführlich:

```
2024-01-15 10:30:00 [INFO] Starte E-Post Fetcher mit 2 Account(s)
2024-01-15 10:30:00 [INFO] Intervall: 900s
2024-01-15 10:30:00 [INFO] Folders: INBOX_FOLDER, ARCHIVE_FOLDER
2024-01-15 10:30:00 [INFO] Metadata speichern: True
2024-01-15 10:30:01 [INFO] [firma-a] Prüfe Folder: INBOX_FOLDER
2024-01-15 10:30:02 [INFO] [firma-a] 3 Brief(e) in INBOX_FOLDER gefunden
2024-01-15 10:30:03 [INFO] [firma-a] Lade herunter: Rechnung vom 2024-01-15 (letter-123)
2024-01-15 10:30:04 [INFO] [firma-a] Gespeichert → /consume/firma-a/letter-123_Rechnung.pdf
```

## Fehlerbehandlung

- Fehlgeschlagene Downloads werden geloggt und übersprungen
- Paging-Fehler brechen die Schleife ab, aber der Fetcher läuft weiter
- API-Fehler werden geloggt und der nächste Account wird versucht
- State-File verhindert doppelte Downloads nach Neustart
