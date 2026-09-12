# IPTV-Org Pilot

A self-hosted FastAPI gateway and channel curator for iptv-org, with SQLite persistence, daily imports, bounded stream checks, M3U exports and filtered XMLTV. The dashboard uses Jinja2, Alpine.js and Tailwind CDN, with local core styles.

## Run locally with Docker

1. Copy `.env.example` to `.env`.
2. Set `ADMIN_PASSWORD` (at least 12 characters) and `EXPORT_TOKEN` (at least 24 characters) to separate random secrets. `openssl rand -hex 32` generates a suitable value. No default credentials are accepted.
3. Run `docker compose up -d --build`.
4. Open `http://localhost:8000` and use the browser's HTTP Basic login with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

The first empty database imports `in,us` channels and checks streams in the background. Failed imports leave the previous database intact; retry from the dashboard. The playlist is empty until streams pass health checks. Every daily sync runs at 03:00 UTC and is followed by a health check; independent checks run every six hours.

## HTTPS with Traefik and Cloudflare

Set `DOMAIN`, `ACME_EMAIL`, and `CF_DNS_API_TOKEN`; set `PUBLIC_BASE_URL=https://your-domain`. Point DNS at this server, allow ports 80/443, then run:

```sh
docker compose --profile tls up -d --build
```

The Cloudflare token needs Zone DNS Edit and Zone Read for the relevant zone. Traefik stores certificates in its named volume. The dashboard uses Basic authentication over TLS. The Docker socket mount gives Traefik sensitive host access; use a restricted Docker socket proxy in hardened environments. Traefik access logging is off to keep export query tokens out of logs. Avoid logging full export URLs in other proxies.

## Configure ingestion and EPG

- `COUNTRIES=in,us`: case-insensitive country allowlist. Blank means all.
- `CATEGORIES=news,sports`: category allowlist. Blank means all. Country and category filters intersect.
- `EPG_URLS=https://your-guide-host/guide.xml`: comma-separated public HTTP(S) XMLTV or gzip XMLTV sources. Run the upstream [iptv-org EPG generator](https://github.com/iptv-org/epg) separately if you need to generate guides. No guide subscription or fabricated programme data is included.
- `CHECK_CONCURRENCY=20`, `CHECK_TIMEOUT=5`, `HEALTH_INTERVAL_HOURS=6` control checking.
- `MAX_DOWNLOAD_BYTES=67108864` bounds each upstream document, including decompressed XMLTV. Guides cache for one hour. Source errors return HTTP 502; without sources, `/epg.xml` is a valid channel-only guide.

The importer uses the official [channels, streams, logos and feeds APIs](https://github.com/iptv-org/api). Canonical IDs are authoritative. Streams without IDs attach by unambiguous normalized names, removing quality labels. With no filters, unmatched titles receive deterministic synthetic IDs. Conflicting canonical IDs are never merged by name. Duplicate URLs per channel collapse into one mirror. Existing numbers, names, group names, enablement, and EPG overrides survive synchronization. Removed upstream mirrors are deleted; channel records remain for curation. Changing filters replaces the active imported mirror set, not a cumulative union. New channels get the next unused number after the maximum; editing to an occupied number returns 409.

Only enabled channels with ONLINE streams appear in either export. The lowest-latency online mirror is chosen deterministically, preserving explicit `tvg-chno` values. A channel's XMLTV override must match the source guide's channel ID. Duplicate programme slots are removed. Stream referrer and user-agent requirements are checked and emitted as VLC options; support varies by TV app.

## API

Admin endpoints require HTTP Basic credentials. Mutations additionally require `X-Pilot-Request: 1` to prevent cross-origin browser form submissions.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Counts, last successful sync, current job and EPG configuration |
| GET | `/api/channels?q=&status=ONLINE&page=1&limit=50` | Paginated channel metadata and stream health |
| PATCH | `/api/channels/{id}` | Edit number, name, TV name, group, EPG override, enablement |
| POST | `/api/sync` | Queue import and check; optional JSON `countries` and `categories` arrays |
| POST | `/api/check` | Queue all-stream health check |
| GET | `/playlist.m3u?token=...` | Player-ready M3U |
| GET | `/epg.xml?token=...` | Matching XMLTV |
| GET | `/healthz` | Database readiness without secrets |

Jobs return 202 immediately, and 409 if another job is running. Poll `/api/status` to inspect completion or failure. Manual filter overrides apply to that job only; scheduled sync uses environment settings. Copy the full token-bearing export URLs from the dashboard into SIPTV, IBO Player, Jellyfin's M3U tuner / XMLTV settings, or VLC's network stream dialog.

## Development and verification

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/uvicorn app.main:app --reload --no-access-log
```

Provide credentials in `.env` before starting the app. Run **one worker and one replica**: SQLite writes and the in-process scheduler/job coordinator are designed for one process. The schema is initialized on first startup; future schema changes require explicit migrations before upgrading existing volumes. Back up the database using SQLite's backup API (or stop the service before copying the entire volume); WAL files must not be ignored in a live file copy.

Health checking uses a ranged GET with a total deadline, reads at most a small chunk, and bounds concurrent requests and task batches. ONLINE indicates HTTP reachability with a response body, not successful video decoding; geo-blocking and player restrictions can differ from the server's results. The service exports upstream URLs; it does not proxy video or perform failover during playback.

Outbound requests reject non-HTTP schemes, credential-bearing URLs, private/reserved address resolutions and private redirect targets. DNS validation and the HTTP connection use separate resolutions: use an outbound firewall/proxy to enforce private-network denial at connection time against DNS rebinding. Public guide hosts are required. Dashboard assets load from CDN as requested; core styling is local, but Alpine interactions need CDN availability.

## Project layout

`app/models.py` and `database.py` define persistence; `services/` holds ingestion, health checks, exports and job coordination; `routers/` exposes the protected API, dashboard and player endpoints. `tests/test_pilot.py` exercises integration and failure paths without live upstream dependencies.
