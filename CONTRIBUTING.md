# Contributing

Thanks for your interest in improving IPTV-Org Pilot. Bug reports, fixes, and feature contributions are all welcome.

## Prerequisites

- Python 3.12
- [uv](https://github.com/astral-sh/uv) for dependency management

## Development setup

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

## Running the app locally

```sh
.venv/bin/uvicorn app.main:app --reload --no-access-log
```

Provide credentials in `.env` first (copy `.env.example`); see the "Run locally with Docker" and "Development and verification" sections of [README.md](README.md) for details.

## Running tests

```sh
.venv/bin/pytest
```

Tests live in `tests/test_pilot.py` (pytest + pytest-asyncio, fixtures defined inline). Add or extend tests there when you change behavior.

## Linting

```sh
.venv/bin/ruff check .
```

The project uses a 120-character line length and the `E4`, `E7`, `E9`, `F` rule sets (see `pyproject.toml`). There is no configured code formatter (no Black, no Prettier), so don't reformat files beyond what's needed for your change.

## Project layout

See the "Project layout" section of [README.md](README.md) for an overview of `app/models.py`, `database.py`, `services/`, `routers/`, and `tests/test_pilot.py`.

## Commit messages

Commits in this repo follow [Conventional Commits](https://www.conventionalcommits.org/) style: a short imperative summary line prefixed with a type such as `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, or `chore:`. For multi-part changes, follow the summary with a bullet list of the sub-changes.

## Security-sensitive areas

`app/services/http_service.py` (outbound HTTP) and the XMLTV parsing path deliberately reject non-HTTP schemes, credential-bearing URLs, and private/reserved address resolutions, and use `defusedxml` for parsing untrusted guide data. If your change touches either area, preserve these protections; see the "Development and verification" section of README.md for the full rationale.

## Submitting changes

1. Fork or branch from `main`.
2. Keep pull requests focused on a single change.
3. Before opening a PR, make sure `pytest` and `ruff check .` both pass locally (there is no CI configured yet to catch this automatically).
4. Fill out the pull request template.

`main` is protected: direct pushes aren't allowed, and every pull request needs an approving review from a code owner (see `.github/CODEOWNERS`) before it can merge.

## License

By contributing, you agree that your contributions will be licensed under this project's [MIT License](LICENSE).
