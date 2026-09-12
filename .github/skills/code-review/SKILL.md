---
name: code-review
description: Repository-specific guidance for reviewing pull requests to IPTV-Org Pilot. Use this whenever reviewing a pull request in this repository.
---

IPTV-Org Pilot is a self-hosted, single-admin FastAPI app (async SQLAlchemy + SQLite) that syncs IPTV channels and serves M3U/XMLTV exports. Review PRs against these repo-specific facts rather than generic best practices alone.

## Security-sensitive areas — scrutinize changes here closely

- `app/services/http_service.py`: outbound requests must keep rejecting non-HTTP schemes, credential-bearing URLs, and private/reserved address resolutions (SSRF protection). Any change here needs a strong justification.
- EPG/XMLTV parsing (`app/services/export_service.py`, `defusedxml`): guide documents come from user-configured but otherwise untrusted URLs. Never switch parsing to `xml.etree.ElementTree.fromstring` directly on untrusted input, and never re-enable entity resolution.
- `app/auth.py`: session validity depends on both a password fingerprint and a `session_generation` counter (bumped on explicit password changes so a session can't become valid again if the password is later reverted to an old value — see PR #1). Any change to session signing/validation must preserve both checks, not just one.
- Every token comparison (`export_auth`, `profile_export_auth`, `verify_password`) must use `secrets.compare_digest`, never `==`.
- Secrets (passwords, API keys, tokens) are never returned from any `GET`/status endpoint — only booleans like `password_locked` or `api_key_set`. Flag any new endpoint that echoes a secret back.
- `ADMIN_PASSWORD`/`EXPORT_TOKEN` set via environment always override the database-stored value (see `resolve_credentials`); any account-mutation endpoint must check `settings.<field> is not None` and refuse the change (409) rather than silently no-op.

## Architectural conventions — flag deviations

- DB access: reads use `async with db.sessions() as session`, writes use `async with db.sessions.begin() as session` (auto commit/rollback). No manual `session.commit()`.
- Relationships accessed after a session closes (e.g. in a route handler, after the `async with` block) must be eager-loaded with `selectinload(...)` inside that session first, or SQLAlchemy will raise `MissingGreenlet`.
- Admin-only JSON endpoints live under `/api`, gated with `dependencies=[Depends(admin)]` at the router level; non-`GET`/`HEAD`/`OPTIONS` requests additionally require the `X-Pilot-Request: 1` header (CSRF defense-in-depth). New mutating endpoints should follow this, not invent a new auth check.
- No service layer for simple CRUD — SQL/logic lives directly in the route handler (see `app/routers/api.py`, `app/routers/profiles.py`). `IntegrityError` is caught per-endpoint and translated to `409`; don't ask for a shared exception-handling abstraction for 2-3 occurrences of this.
- New SQLAlchemy models go in `app/models.py`; there is no migration framework (`Base.metadata.create_all` only adds missing tables on startup), so a new table is fine but altering an existing column needs an explicit note in the PR about upgrade impact on existing SQLite files.

## Style

- Ruff-only, config in `pyproject.toml` (`E4`, `E7`, `E9`, `F`, line-length 120). No Black/Prettier — don't request reformatting beyond what's needed for the change.
- No docstrings or comments explaining *what* code does; a comment is only warranted for a non-obvious *why* (a hidden constraint, a workaround, a security rationale). Flag comments that just restate the code.
- Frontend (`app/templates/index.html`, `app/static/pilot.js`, `app/static/pilot.css`) has no build step and no component framework beyond Alpine.js + Tailwind CDN — don't suggest introducing one for a small UI change.

## Tests

- All tests live in `tests/test_pilot.py` (pytest + pytest-asyncio), using the `settings`/`db` fixtures, the `seed()`/`login()` helpers, and `TestClient(create_app(settings))` for end-to-end HTTP-level tests. A new endpoint or behavior change should extend this file rather than introduce a new test module or a mocking framework.
- A security-relevant fix (auth, tokens, sessions) should come with a regression test that reproduces the specific attack/failure scenario, not just a happy-path check.
