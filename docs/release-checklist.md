# Release checklist

## Source and policy

- [ ] Version is consistent in `app/_version.py`, CLI, package metadata, image labels, and status.
- [ ] `CHANGELOG.md` reflects the actual implementation and known limitations.
- [ ] MIT license and dependency/model licenses were reviewed.
- [ ] Dependabot alerts and pending dependency security updates were reviewed.
- [ ] No real document, `.env`, token, database, backup, cache, or model artifact is tracked.
- [ ] Secret scan passed and the security policy is reachable.

## Quality

- [ ] Unit and integration tests passed on Python 3.12.
- [ ] Ruff lint and format checks passed.
- [ ] MCP tool list, authentication, bounded search call, and refresh smoke tests passed.
- [ ] Runtime container vulnerability/configuration scan passed or findings are documented.
- [ ] README critical commands and both Compose configurations parse successfully.

## Deployment

- [ ] Fresh lexical install was tested from a clean checkout without host Python.
- [ ] Optional semantic install, model persistence, Qdrant health, and lexical fallback were tested.
- [ ] `linux/amd64` and `linux/arm64` runtime images built.
- [ ] Oracle Cloud Ubuntu instructions and loopback-only port binding were reviewed.
- [ ] Restart persistence and backup/restore were verified with synthetic data.
- [ ] Upgrade from the previous release and rollback were verified.

## Publication (explicit maintainer approval required)

- [ ] Release commit was reviewed.
- [ ] Signed `v0.1.0` tag was created.
- [ ] Multi-architecture image has immutable `0.1.0`, moving `0.1`, and documented `latest` tags.
- [ ] GitHub release notes link to the changelog and list known limitations.
- [ ] Fresh installation was repeated using published artifacts.
