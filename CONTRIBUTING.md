# Contributing

Thank you for improving Private Document Gateway. Keep changes focused on the self-hosted
document conversion, indexing, retrieval, security, and operations scope.

## Development workflow

1. Open an issue for behavior changes or large design decisions.
2. Fork the repository and create a focused branch.
3. Install Python 3.12 and `pip install -e '.[semantic,dev]'`.
4. Add or update tests with the implementation.
5. Run `ruff check .`, `ruff format --check .`, and `pytest --cov=app`.
6. Verify `docker compose config --quiet` for deployment changes.
7. Submit a pull request using the repository template.

Do not commit real documents, credentials, `.env`, model caches, databases, or generated
backups. Synthetic fixtures must be small and contain no personal data. New dependencies need a
clear product reason and a compatible open-source license.

Security vulnerabilities must follow [SECURITY.md](SECURITY.md), not a public issue.

## Design expectations

- Preserve bounded retrieval; no MCP tool should return a complete raw document by default.
- Keep lexical search usable without semantic dependencies.
- Keep document content local and telemetry disabled.
- Prefer existing interfaces and adapters over vendor coupling.
- Avoid breaking MCP response fields within the `0.1.x` line unless required for security.

By participating, you agree to [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
