# Security fix reference

Date: 2026-08-12
Branch: `security-fix`

## Critical changes

### Authentication and sessions

- Registration now returns the same HTTP `202` acknowledgement for new and
  existing email addresses and does not create an authenticated session. The
  frontend redirects to explicit sign-in after registration.
- Password hashing happens before the existing-account lookup, and concurrent
  unique-email conflicts are converted to the same generic registration
  outcome.
- Login tokens carry the persisted `users.session_version`. Logout increments
  that version before deleting the cookie, so a copied pre-logout token cannot
  be replayed.
- The development full-access provisioner verifies the resolved account is an
  admin after both direct creation and conflict-reload paths. Missing and
  non-admin fallback accounts receive no privilege bundle.

Compatibility note: clients must treat registration as an acknowledgement,
not an authenticated `AuthResponse`. Clean installations receive
`users.session_version` from `0001_initial.py`.

### Trusted proxy boundary

- Authentication rate-limit identity uses `X-Forwarded-For` only when the
  direct peer belongs to `TRUSTED_PROXY_CIDRS`; the chain is walked from the
  trusted edge to the first untrusted address.
- Production configuration rejects missing, malformed, IPv4 catch-all
  (`0.0.0.0/0`), and IPv6 catch-all (`::/0`) trust sets.
- ECS frontend proxy tasks now use dedicated `frontendProxySubnetIds`.
  `TRUSTED_PROXY_CIDRS` is derived only from those subnet CIDRs, not from the
  full VPC. Deployment validation requires TCP 8000 ingress to match the same
  CIDRs exactly and rejects IPv6, prefix-list, or security-group sources on
  that API ingress path.
- Existing ECS services receive their configured network placement during
  updates, so the subnet split is not limited to newly created services.

Deployment note: `infra/aws/config.json` must define at least two dedicated,
non-overlapping `frontendProxySubnetIds`, and the configured ECS security group
must expose API port 8000 only to those subnet CIDRs.

### Resource and tenant allocation bounds

- Website acquisition enforces independent wire and decoded-document limits.
- Workspace creation is serialized per account with the shared
  `workspace.create` PostgreSQL advisory-lock namespace. Explicit creation is
  capped by config-owned policy, and personal-workspace ensure uses the same
  lock so the two paths cannot race past the membership check.

### Export safety

- Audit CSV output sends every cell through the shared spreadsheet-formula
  neutralizer. Regression assertions compare the complete prefixed values so
  sanitization cannot silently truncate attacker-controlled content.

## Finding disposition

Nine attached findings were applicable and fixed. The request for a new
post-`0001` Alembic revision was not applied: CiteLadder is pre-launch, has no
durable production schema, and repository invariant 16 requires all schema
changes to remain folded into `0001_initial.py`. Before the first durable
deployment, freeze that baseline; after that policy transition, every schema
change must use an additive migration with an explicit backfill and downgrade.

## Verification record

- Focused backend security/auth/workspace/export/provisioning tests:
  `78 passed`; the shared component-auth fixture refactor then passed all `151`
  affected component tests.
- Frontend registration/login tests: `8 passed`.
- Changed-path Ruff, `mypy app`, and complexity-policy checks: passed.
- Frontend ESLint, TypeScript, architecture/design policy, and production build:
  passed.
- `alembic upgrade head` plus `alembic check` against a disposable database:
  passed with no new upgrade operations detected.
- Documentation validation, PowerShell parsing, example JSON parsing, and
  `git diff --check`: passed.

The pull request CI remains the authority for the complete backend/frontend
test suites and dependency/secret scans.
