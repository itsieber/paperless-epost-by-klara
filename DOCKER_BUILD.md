# Docker Build Configuration

## Übersicht

Der Docker-Build für den E-Post Fetcher wurde in GitHub Actions ausgelagert. Das Image wird automatisch gebaut und in der GitHub Container Registry (ghcr.io) gespeichert.

## Automatischer Build

Der Build wird automatisch ausgelöst:
- Bei jedem Push auf `main` oder `master` Branch
- Bei Pull Requests
- Bei Tags mit `v*` Muster (z.B. `v1.0.0`)

## Container Registry

Das fertige Image wird hier publiziert:
```
ghcr.io/paperless-epost-by-klara/epost-fetcher:latest
```

Weitere verfügbare Tags:
- `main` / `master` - Latest Build vom entsprechenden Branch
- `sha-<commit>` - Build von einem spezifischen Commit
- `v1.0.0`, `v1.0`, `v1` - Semantic Versioning Tags

## Lokale Entwicklung

Für die lokale Entwicklung kann das Image weiterhin lokal gebaut werden:

```bash
cd epost-fetcher
docker build -t epost-fetcher:dev .
```

Dann in der `docker-compose.yml` temporär anpassen:
```yaml
epost-fetcher:
  image: epost-fetcher:dev
  # statt ghcr.io/paperless-epost-by-klara/epost-fetcher:latest
```

Oder lokal bauen mittels:
```yaml
epost-fetcher:
  build: ./epost-fetcher
```

## Image pullen

Falls das Image noch nicht verfügbar ist oder aktualisiert werden soll:

```bash
docker pull ghcr.io/paperless-epost-by-klara/epost-fetcher:latest
```

## Berechtigungen

Das Image ist öffentlich und kann ohne Authentifizierung gepullt werden. Für private Repositories wäre ein Login erforderlich:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```
