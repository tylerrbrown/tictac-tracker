# Tic Tac Tracker

A web app to track repeating tasks/medications with configurable interval timers.

## Architecture

- **Frontend:** `index.html` (landing + tracker page), `admin.html` (admin panel)
- **Backend:** Python stdlib `http.server` + SQLite — zero dependencies
- **Real-time:** SSE (Server-Sent Events) for live updates across tabs/devices
- **Server:** Ubuntu 22.04 ARM64 EC2 instance (`haproxy` / `34.204.39.160`)
- **Reverse proxy:** HAProxy with SSL termination (wildcard cert `*.tylerrbrown.com`)
- **App port:** 5050 (localhost only, accessed via HAProxy)
- **Service:** systemd `tictac.service`
- **Repo:** https://github.com/tylerrbrown/tictac-tracker

## Files

| File | Description |
|------|-------------|
| `app.py` | Backend server — routing, DB, SSE, all API endpoints |
| `index.html` | Landing page (tracker grid) + tracker page (timer/history) |
| `admin.html` | Admin panel — tracker CRUD, entry management, tools |
| `tictac.service` | systemd service file |

## URLs

- **Landing:** `https://tictac.tylerrbrown.com/` — shows all trackers
- **Tracker:** `https://tictac.tylerrbrown.com/?name=tic-tac` — individual tracker
- **Admin:** `https://tictac.tylerrbrown.com/admin?k=SECRET` — admin panel

### Auth Model

| Endpoint | Auth required? |
|----------|---------------|
| `GET /` (landing) | No |
| `GET /?name=X` (tracker page) | No |
| `GET /api/trackers`, `GET /api/tracker/<slug>` | No |
| `GET /api/entries?name=X` | No |
| `POST /api/entries?name=X` (log entry) | No |
| `DELETE /api/entries/<id>` (delete one) | No |
| `GET /api/events` (SSE stream) | No |
| `GET /admin` | **Yes** (`?k=SECRET`) |
| `POST /api/trackers` (create) | No |
| `PUT/DELETE /api/trackers/*` | **Yes** |
| `DELETE /api/entries?name=X` (bulk delete) | **Yes** |
| `PUT /api/entries/<id>` (edit timestamp) | **Yes** |
| `GET /api/export/<slug>` | **Yes** |
| `GET /api/backup`, `POST /api/restore` | **Yes** |

Secret key: `x9f2k7m4-b8c1-e3a5-d6w0-q7r9s2t4u1v8`

## Database

SQLite at `/opt/tictac-tracker/tictac.db` (or `./tictac.db` locally).

### Tables

**`trackers`** — tracker configuration registry
```sql
CREATE TABLE trackers (
  slug TEXT PRIMARY KEY,           -- normalized name (lowercase, hyphens)
  display_name TEXT NOT NULL,      -- human-readable name
  interval TEXT NOT NULL DEFAULT '3.5d',
  color TEXT NOT NULL DEFAULT 'orange',
  verb TEXT NOT NULL DEFAULT ''    -- button text (e.g. "Took vitamins"), auto-generated via Claude Haiku API
)
```

**`entries`** — individual log entries
```sql
CREATE TABLE entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts BIGINT NOT NULL,              -- Unix timestamp in milliseconds
  tracker TEXT NOT NULL DEFAULT 'tictac'  -- references trackers.slug
)
```

### Migration

On startup, `seed_trackers()` scans `entries` for distinct tracker slugs and auto-creates any missing `trackers` rows with default settings. This ensures backward compatibility with pre-registry data.

## API Endpoints

### Trackers
- `GET /api/trackers` — list all trackers with stats (entry count, last entry)
- `GET /api/tracker/<slug>` — single tracker config + stats
- `POST /api/trackers` — create tracker `{display_name, interval, color}`
- `PUT /api/trackers/<slug>` — update tracker (rename/color/interval). Rename updates entries too.
- `DELETE /api/trackers/<slug>` — delete tracker + all its entries

### Entries
- `GET /api/entries?name=X` — list entries for tracker (JSON array of `{id, ts}`)
- `POST /api/entries?name=X` — add entry (server-generated timestamp)
- `PUT /api/entries/<id>` — update entry timestamp (body: `{"ts": <epoch_ms>}`)
- `DELETE /api/entries/<id>` — delete single entry
- `DELETE /api/entries?name=X` — bulk delete all entries for tracker

### Tools
- `GET /api/export/<slug>?format=csv|json` — export entries
- `GET /api/backup` — download full SQLite DB file
- `POST /api/restore` — upload SQLite DB to replace current

### SSE
- `GET /api/events` — Server-Sent Events stream
- Events: `entry-added`, `entry-deleted`, `entry-updated`, `entries-cleared`, `tracker-created`, `tracker-updated`, `tracker-deleted`, `db-restored`
- Each event payload includes tracker slug for client-side filtering
- 30-second heartbeat keeps connections alive

## App Logic

### Landing Page (`/`)
- Explains how the system works (3-step guide)
- Create a Tracker form: name, interval, color picker
- On creation: shows the tracker URL with Copy URL + Open Tracker buttons
- "Create Another" to reset the form
- No auth required — anyone on the page can create a tracker

### Tracker Page (`/?name=X`)
- Loads config from `/api/tracker/<slug>` (interval, color from DB, not URL)
- **Green** (ready): elapsed >= interval — show "take it" button
- **Colored** (wait): elapsed < interval — show live countdown
- Button POSTs new entry, resets timer
- History log with per-entry delete
- SSE listener for live cross-tab updates
- "Back to All Trackers" link at top

### Admin Page (`/admin?k=SECRET`)
- Dashboard: tracker count + total entry count
- Tracker list with Edit/Delete/Copy URL buttons per tracker
- Create New Tracker form (name, interval, color picker)
- Tap tracker → expand entry list (paginated, 20/page)
- Entry management: delete individual, bulk delete all, add manual entry with custom timestamp
- Tools: Export (CSV/JSON), Backup DB, Restore DB
- SSE listener for real-time updates
- Confirmation modals for destructive actions

## Server Deployment

Files on server: `/opt/tictac-tracker/` (cloned from GitHub repo)

```bash
# Update
cd /opt/tictac-tracker && git pull && systemctl restart tictac

# Logs
journalctl -u tictac -f

# Service management
systemctl status|start|stop|restart tictac
```

## HAProxy Config

In `frontend inbound`:
```
acl host_tictac hdr_beg(host) -i tictac.tylerrbrown.com
use_backend web-tictac if host_tictac
```

Backend:
```
backend web-tictac
        server tictac 127.0.0.1:5050 check fall 3 rise 1
```

## DNS

- GoDaddy: `tictac.tylerrbrown.com` CNAME → `pxy.tylerrbrown.com`
- Pi-hole: needs local DNS override or cache flush after changes
- Wildcard `*.tylerrbrown.com` points to `aws.tyware.com` (different IP) — specific records needed

## Server Constraints

- **t4g.nano-class** — 418MB total RAM, no swap. Very tight.
- `apt install` can be OOM-killed — use Python for DB operations instead of installing CLI tools
- `sqlite3` CLI is not installed; use `python3 -c "import sqlite3; ..."` for migrations
- Tailscale (`tailscaled`) uses ~49MB — largest non-kernel consumer
- SSE connections each hold a thread — fine for single-user with a few tabs

## Decisions

- **Obscurity-by-subdomain** for tracker pages — no auth needed to view/use trackers
- **Admin key** only for admin page and destructive/management operations
- **Tracker registry** in DB — interval/color stored server-side, not in URL params
- **SSE** for real-time — works with Python stdlib, no WebSocket library needed
- Zero Python dependencies — uses stdlib `http.server` + `sqlite3`
- SQLite with WAL mode for concurrent reads
- GitHub Pages deployment abandoned (CORS issues with external DB services)

## Color Presets

orange, red, yellow, lime, green, teal, cyan, blue, indigo, purple, pink, rose, gray, brown, gold
