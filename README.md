# IPTV-Org Pilot

A self-hosted FastAPI gateway and channel curator for iptv-org, with SQLite persistence, daily imports, bounded stream checks, M3U exports and filtered XMLTV. The dashboard uses Jinja2, Alpine.js and Tailwind CDN, with local core styles.

## Run locally with Docker

1. Run `docker compose up -d --build` with no `.env` at all, or one that leaves `ADMIN_PASSWORD`/`EXPORT_TOKEN` blank.
2. Open `http://localhost:8000`. With no admin account configured yet, this redirects to a one-time setup wizard: pick an admin username and password (at least 12 characters); a random export token is generated for you. Whoever reaches `/setup` first becomes the admin, so don't expose the port to an untrusted network before finishing this step.
3. The wizard signs you straight in. Later visits use the `/login` page (a signed, `HttpOnly` session cookie, not a browser Basic-auth popup); `/logout` clears it. Changing the admin password invalidates any sessions issued under the old one.

Alternatively, skip the wizard entirely by copying `.env.example` to `.env` and setting `ADMIN_PASSWORD` (at least 12 characters) and `EXPORT_TOKEN` (at least 24 characters) to separate random secrets yourself (`openssl rand -hex 32` generates a suitable value) before the first start. Whichever path is used first "wins": once credentials exist (via `.env` or the wizard), `/setup` redirects to the dashboard and cannot be re-run.

The first empty database imports `in,us` channels and checks streams in the background. Failed imports leave the previous database intact; retry from the dashboard. The playlist is empty until streams pass health checks. Sync runs on a fixed interval (`SYNC_INTERVAL_HOURS`, default 24) starting from process startup, not a fixed clock time, and is followed by a health check; independent checks run on their own interval (`HEALTH_INTERVAL_HOURS`, default 6).

## HTTPS with Traefik and Cloudflare

Set `DOMAIN`, `ACME_EMAIL`, and `CF_DNS_API_TOKEN`. Point DNS at this server, allow ports 80/443, then run:

```sh
docker compose --profile tls up -d --build
```

The Cloudflare token needs Zone DNS Edit and Zone Read for the relevant zone. Traefik stores certificates in its named volume. The dashboard's session cookie is marked `Secure` automatically once requests arrive over HTTPS (via `X-Forwarded-Proto`). The Docker socket mount gives Traefik sensitive host access; use a restricted Docker socket proxy in hardened environments. Traefik access logging is off to keep export query tokens out of logs. Avoid logging full export URLs in other proxies.

## Configure ingestion and EPG

- `COUNTRIES=in,us`: case-insensitive country allowlist. Blank means all.
- `CATEGORIES=news,sports`: category allowlist. Blank means all. Country and category filters intersect.
- `EPG_URLS=https://your-guide-host/guide.xml`: comma-separated public HTTP(S) XMLTV or gzip XMLTV sources. Run the upstream [iptv-org EPG generator](https://github.com/iptv-org/epg) separately if you need to generate guides. No guide subscription or fabricated programme data is included.
- `CHECK_CONCURRENCY=20`, `CHECK_TIMEOUT=5`, `HEALTH_INTERVAL_HOURS=6` control checking.
- `SYNC_INTERVAL_HOURS=24` controls how often the full upstream sync (new/removed channels, not just stream health) repeats. Set it to `3` for a sync every three hours, for example.
- `MAX_DOWNLOAD_BYTES=67108864` bounds each upstream document, including decompressed XMLTV. Guides cache for one hour. Source errors return HTTP 502; without sources, `/epg.xml` is a valid channel-only guide.

The importer uses the official [channels, streams, logos and feeds APIs](https://github.com/iptv-org/api). Canonical IDs are authoritative. Streams without IDs attach by unambiguous normalized names, removing quality labels. With no filters, unmatched titles receive deterministic synthetic IDs. Conflicting canonical IDs are never merged by name. Duplicate URLs per channel collapse into one mirror. Existing numbers, names, group names, enablement, and EPG overrides survive synchronization. Removed upstream mirrors are deleted; channel records remain for curation. Changing filters replaces the active imported mirror set, not a cumulative union. New channels get the next unused number after the maximum; editing to an occupied number returns 409.

Only enabled channels with ONLINE streams appear in either export. The lowest-latency online mirror is chosen deterministically, preserving explicit `tvg-chno` values. A channel's XMLTV override must match the source guide's channel ID. Duplicate programme slots are removed. Stream referrer and user-agent requirements are checked and emitted as VLC options; support varies by TV app.

Playlist and guide URLs use the hostname of the incoming request (via `X-Forwarded-Host`/`X-Forwarded-Proto` when set by a reverse proxy, otherwise the request's own host), so they always match whatever domain or address you actually connected through.

## Jellyfin Live TV integration

From the dashboard's "Connect to Jellyfin" panel, enter Jellyfin's server URL, an admin API key (create one under Jellyfin's Dashboard → API Keys), and the URL this app should tell Jellyfin to use for the playlist/guide (defaults to the current page's origin; use an internal address like `http://iptv-gtw:8000` if both containers share a Docker network, so Jellyfin doesn't depend on a public hostname or TLS). Saving tests the connection; "Push now" registers (or updates in place) an M3U tuner and XMLTV listings provider in Jellyfin and triggers its "Refresh Guide" task immediately. Tick "push automatically" to also push after every sync/check job completes, including the scheduled ones — this drives Jellyfin's Live TV entirely from the dashboard instead of adding the M3U/XMLTV URLs by hand in Jellyfin.

## API

Admin endpoints require a signed-in session cookie (set by `/login`, cleared by `/logout`). Mutations additionally require `X-Pilot-Request: 1` to prevent cross-origin browser form submissions.

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/login` | Sign-in page and session creation |
| POST | `/logout` | Clear the session cookie |
| GET/POST | `/setup` | One-time admin account creation when none exists yet (no auth required) |
| GET | `/api/status` | Counts, last successful sync, current job and EPG configuration |
| GET | `/api/filters` | Distinct countries, languages and groups present, for dashboard filter dropdowns |
| GET | `/api/channels?q=&status=ONLINE&country=&language=&group_title=&page=1&limit=50` | Paginated channel metadata and stream health |
| PATCH | `/api/channels/{id}` | Edit number, name, TV name, group, EPG override, enablement |
| POST | `/api/sync` | Queue import and check; optional JSON `countries` and `categories` arrays |
| POST | `/api/check` | Queue all-stream health check |
| GET/POST | `/api/jellyfin` | Read or save the Jellyfin connection (API key never returned) |
| POST | `/api/jellyfin/push` | Push the current M3U/XMLTV URLs to Jellyfin now |
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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, running tests/lint, and the PR process.
