# Security policy

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public GitHub issue, discussion, pull request, or
chat transcript. Use the repository's **Security → Report a vulnerability** private reporting
form. Include the affected version, deployment mode, impact, reproduction steps, and a minimal
proof of concept that contains no real documents or secrets.

If private vulnerability reporting is not enabled for the repository, contact the maintainer
through a private channel listed on the GitHub profile and ask for a secure reporting route before
sharing technical details.

The maintainer should acknowledge a complete report within seven days, coordinate remediation,
and credit the reporter unless anonymity is requested. Do not test against systems you do not own
or have explicit permission to assess.

## Supported versions

Until `1.0.0`, only the latest released minor version receives security fixes. Operators should
backup persistent data before upgrading and subscribe to repository release notifications.

## Dependency maintenance

The repository uses Dependabot to propose weekly updates for Python dependencies, container
images, Docker Compose services, and GitHub Actions. Dependabot alerts and security updates should
remain enabled in the repository's **Settings → Advanced Security** page. Automated pull requests
are reviewed and tested before merge; automatic merging is intentionally not part of the policy.

Dependabot complements, rather than replaces, the CI container vulnerability scan and secret
scan. Maintainers should review unresolved alerts before each release and document any accepted
risk in the release notes.

## Deployment boundary

CorpusGate protects its own HTTP/MCP surface and file roots. The operator remains
responsible for host patching, Docker security, Tailscale/HTTPS access policy, credential storage,
backups, and limiting access to the Oracle Cloud account and VM.
