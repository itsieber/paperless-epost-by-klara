# Nextcloud Stack

Vollständiger Docker-Stack mit:
- **Nextcloud** (+ MariaDB, Elasticsearch, AppAPI DSP)
- **OnlyOffice** Dokumentenserver
- **Roundcube** Webmail
- **Coturn** TURN-Server für Nextcloud Talk
- **Paperless-ngx** (+ PostgreSQL, Redis, Gotenberg, Tika)
- **E-Post Fetcher** (holt PDFs automatisch von mehreren E-Post Accounts)

---

## Setup

### 1. Repo klonen
```bash
git clone https://github.com/dein-user/nextcloud-stack.git
cd nextcloud-stack
```

### 2. Umgebungsvariablen setzen
```bash
cp .env.example .env
nano .env   # alle Werte ausfüllen
```

Paperless Secret Key generieren:
```bash
openssl rand -hex 32
```

### 3. Consume-Ordner anlegen
```bash
mkdir -p /opt/paperless/consume
```

### 4. Stack starten
```bash
docker compose up -d
```

---

## E-Post Fetcher

Der Fetcher holt automatisch alle Briefe aus konfigurierten E-Post Accounts
und legt sie als PDF in Unterordner des Paperless Consume-Verzeichnisses:

```
/opt/paperless/consume/
  ├── firma-a/    → wird von Paperless als eigene Inbox verarbeitet
  ├── firma-b/
  └── firma-c/
```

**Accounts konfigurieren** in `.env`:
```
EPOST_ACCOUNTS=[{"key":"API_KEY_1","name":"firma-a"},{"key":"API_KEY_2","name":"firma-b"}]
```

**Paperless Consumption Templates** (Web-UI):
`Settings → Consumption Templates` → pro Unterordner Tags/Korrespondenten zuweisen.

---

## Portainer Deployment

```
Stacks → Add Stack → Git Repository
  URL:          https://github.com/dein-user/nextcloud-stack
  Branch:       main
  Compose path: docker-compose.yml
```

Secrets unter **Environment variables** in Portainer eintragen —
niemals die `.env` Datei committen!

---

## Ports

| Service       | Port  |
|---------------|-------|
| Nextcloud     | 2020  |
| OnlyOffice    | 2021  |
| Roundcube     | 2022  |
| Paperless-ngx | 2023  |
| TURN (TCP)    | 3478  |
| TURN (UDP)    | 3478  |
| TURN TLS      | 5349  |
