# Update and rollback

Documents are the primary data source. Markdown cache and vectors are rebuildable; SQLite still
contains authoritative metadata and should always be backed up before a version change.

## Update

```bash
./pdg version
./pdg backup
git fetch --tags
git checkout vNEW_VERSION
docker compose build --pull gateway
docker compose run --rm --no-deps gateway private-document-gateway-admin doctor
docker compose up -d
./pdg status
./pdg list-documents --limit 1
```

Starting the new image applies only idempotent, versioned SQLite migrations. It never silently
deletes older data. A database with a newer unsupported schema causes startup to stop with a safe
error. Keep the backup until retrieval and MCP authentication have been verified.

For semantic deployments, use both Compose files for build/start and run `./pdg reindex
--semantic` only when the changelog says model/vector compatibility changed.

## Rollback

Stop writes first. If the old application supports the current schema, select the previous tag and
start it against the same volumes:

```bash
docker compose stop gateway
git checkout vPREVIOUS_VERSION
docker compose build gateway
docker compose up -d
./pdg status
```

If startup reports a newer schema, do not edit SQLite by hand. Restore the pre-update backup while
the gateway is stopped:

```bash
docker compose stop gateway
./pdg restore /backups/pdg-backup-TIMESTAMP.tar.gz --confirm-restore
docker compose start gateway
./pdg status
```

Never use `docker compose down -v` during update or rollback; it deletes named persistent data.
