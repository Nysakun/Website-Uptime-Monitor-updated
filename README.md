# Website Uptime Monitor

A Python tool that checks whether domains, IP addresses and URLs are UP or DOWN,
stores every check in a database, and explains problems in plain language.
It works as a command-line tool, a web dashboard, and a REST API that can be
integrated into other services.

## Features
- Checks **domains, IP addresses and full URLs**
- Monitors multiple targets at the same time (multithreading)
- Records status code, response time, resolved IP, timestamp and the reason for failure
- Explains failures in plain language (DNS problem, timeout, SSL issue, server error...)
- Works with **SQLite** (zero setup) or **MySQL** (for production/deployment)
- `--once` for a single check, `--watch` for continuous monitoring, `--report` for an uptime summary
- **Web dashboard**: enter any domain/IP, see a live UP/DOWN report and history
- **Watchlist**: start monitoring a target from the dashboard and the server keeps
  checking it automatically in the background
- **REST API** (FastAPI, with auto-generated docs at `/docs`) so the checker can be
  integrated into another website or service
- **Security**: API key authentication, per-IP rate limiting, and blocking of
  private/internal IP addresses (including through redirects) to prevent misuse
- **Docker-ready**: one command starts the app and a MySQL database together

## Project structure
```
monitor/
  checker.py    - checks one target (domain/IP/URL), handles redirects safely
  diagnose.py   - turns a raw error into a plain-language explanation
  database.py   - storage layer (SQLite or MySQL)
  stats.py      - uptime percentage and statistics
  safety.py     - blocks invalid/private targets (SSRF protection)
  ratelimit.py  - per-IP request limiting
  worker.py     - background thread that checks the watchlist automatically
  api.py        - FastAPI app: REST API + web dashboard
  cli.py        - command-line interface
  static/
    index.html  - the web dashboard
main.py         - CLI entry point
websites.txt    - targets for CLI monitoring
Dockerfile, docker-compose.yml - containerised deployment
```

## Setup (local)
Requires Python 3.10+.

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your own values:
```
DB_ENGINE=sqlite          # or mysql
API_KEY=choose-a-secret-key
MONITOR_INTERVAL=60
```
(MySQL variables are only needed when `DB_ENGINE=mysql` — see `.env.example`.)

## Command-line usage
Add targets to `websites.txt` (one per line: a domain, IP or URL), then:

```bash
python main.py --once                        # check all targets one time
python main.py --once --report               # check, then show the uptime table
python main.py --watch --interval 30         # check every 30 seconds (Ctrl+C to stop)
python main.py --report                      # uptime of ALL targets
python main.py --stats google.com            # detailed uptime for one target
python main.py --history google.com          # recent checks for one target
python main.py --once --file other_list.txt  # use a different list
python main.py --help                        # all options
```

Example `--stats` output:
```
Website: https://google.com

Uptime:       99.42%
Checks:       1,250
Successful:   1,243
Failed:       7
Avg Response: 184ms
```

## Web dashboard and API

Start the server:
```bash
uvicorn monitor.api:app --reload
```
- Dashboard: `http://127.0.0.1:8000`
- API docs (interactive): `http://127.0.0.1:8000/docs`

Every `/api/*` request (except `/api/health`) requires an `X-API-Key` header
matching the `API_KEY` set in `.env`. The dashboard sends this automatically.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Check the API is running |
| `/api/check?target=` | GET | Check a target now and return its full report |
| `/api/report?target=` | GET | Uptime statistics and history (no new check) |
| `/api/watchlist` | GET | List all automatically monitored targets |
| `/api/watchlist` | POST | Start monitoring a target automatically |
| `/api/watchlist?target=` | DELETE | Stop monitoring a target (history is kept) |

## How a target is judged UP or DOWN
- UP: HTTP status 200-399 (redirects are followed)
- DOWN: status 400+, timeout, connection error, SSL error, DNS failure, invalid target

## Design decisions
- Threads check multiple targets at once, since checking is mostly waiting on the network.
- The database layer (`database.py`) supports both SQLite and MySQL behind the
  same functions, so the rest of the app never needs to know which one is active.
- Timestamps are stored in UTC and shown in local time in the CLI and dashboard.
- Average response time counts only successful checks.
- All database queries use placeholders, which prevents SQL injection.
- Redirects are followed manually (not by the HTTP library) so every hop can be
  checked against private/internal IP ranges, preventing the checker from being
  used to probe internal networks (SSRF protection).

## Deployment (Docker)

Requires Docker and Docker Compose.

1. Create a `.env` file (copy `.env.example`) with your own `DB_PASSWORD`,
   `API_KEY` and `MONITOR_INTERVAL`.
2. Run:
```bash
   docker compose up --build -d
```
3. The API and web dashboard are available at `http://<server-address>:8000`.
   API docs: `http://<server-address>:8000/docs`

To stop: `docker compose down` (add `-v` to also delete the database volume).

### Environment variables
| Variable | Purpose |
|---|---|
| `DB_ENGINE` | `mysql` or `sqlite` (default `sqlite`) |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | MySQL connection (only used when `DB_ENGINE=mysql`) |
| `API_KEY` | Required in the `X-API-Key` header for all `/api/*` requests |
| `MONITOR_INTERVAL` | Seconds between automatic checks for watchlisted targets (default 60) | 