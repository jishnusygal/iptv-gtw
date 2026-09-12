# Security Policy

## Reporting a Vulnerability

Report vulnerabilities privately through GitHub: open the "Security" tab on this repository and use "Report a vulnerability" (this opens a private security advisory visible only to the maintainer). Do not open a public issue for a security report.

This is a solo-maintained project. There is no guaranteed response time or fix SLA, but reports will be reviewed and addressed on a best-effort basis, consistent with the no-warranty terms of the [MIT License](LICENSE).

## Supported Versions

There are no tagged releases or version numbers for this project; only the latest commit on `main` is supported. If a report applies to an older commit, update to the latest `main` first to confirm the issue still reproduces.

## Security-sensitive areas

The following areas deliberately implement security protections and deserve extra scrutiny in a report or a fix:

- `app/services/http_service.py` (outbound HTTP): rejects non-HTTP schemes, credential-bearing URLs, and private/reserved address resolutions.
- The XMLTV parsing path: uses `defusedxml` to parse untrusted guide data.
- `app/auth.py`: session and authentication handling.

See the "Development and verification" section of [README.md](README.md) for the full rationale behind these protections, and the "Security-sensitive areas" section of [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance.

## Existing automated scanning

CodeQL analysis runs on every push and pull request to `main`, plus a weekly schedule (`.github/workflows/codeql.yml`), covering both the Python and JavaScript/TypeScript code.
