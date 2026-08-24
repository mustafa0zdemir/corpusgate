# Container publishing policy

No container is published automatically by pull requests, normal pushes, tags, or release drafts.
The `Publish multi-architecture container` workflow is manual, requires an existing reviewed SemVer
tag, and requires the operator to type `PUBLISH`.

For stable `vX.Y.Z` releases it prepares:

- immutable `X.Y.Z`;
- moving compatible-minor `X.Y`;
- `latest` only for a stable, non-prerelease SemVer tag.

Prereleases must never update `latest`. Images target `linux/amd64` and `linux/arm64`, run as
`10001:10001`, and include OCI source/license/version/revision labels plus SBOM and provenance.
Publishing requires explicit maintainer approval and every item in
[the release checklist](release-checklist.md).
