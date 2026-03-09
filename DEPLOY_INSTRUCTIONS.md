# GitHub Action starten

## Änderungen committen und pushen

```bash
# 1. Alle Änderungen zum Staging hinzufügen
git add .github/workflows/docker.yml docker-compose.yml DOCKER_BUILD.md

# 2. Commit erstellen
git commit -m "Auslagern des Docker Builds in GitHub Actions"

# 3. Zum Repository pushen
git push origin main
```

Falls dein Hauptbranch `master` heißt statt `main`:
```bash
git push origin master
```

## Action überwachen

Nach dem Push:

1. Gehe zu deinem GitHub Repository
2. Klicke auf den Tab **"Actions"**
3. Du siehst dort den Workflow **"Build and Push Docker Image"** laufen

## Alternatives Starten per Git Tag

Du kannst auch einen Release-Tag erstellen:

```bash
# Tag erstellen
git tag v1.0.0

# Tag pushen
git push origin v1.0.0
```

Dies startet ebenfalls die Action und erstellt zusätzliche Image-Tags (v1, v1.0, v1.0.0).

## Status überprüfen

Nach erfolgreichem Build kannst du das Image mit folgendem Befehl pullen:

```bash
docker pull ghcr.io/paperless-epost-by-klara/epost-fetcher:latest
```

## Falls die Action fehlschlägt

Überprüfe:
1. GitHub Actions sind im Repository aktiviert
2. GitHub Packages (Container Registry) Berechtigungen sind korrekt
3. Der Workflow hat Schreibrechte für Packages
