# Tic Tac Tracker

A simple web app to track twice-weekly medication ("tic tac") doses with a 3.5-day interval timer.

## Architecture

- **Frontend:** Single `index.html` served by Python's built-in `http.server`
- **Backend:** Python stdlib `http.server` + SQLite — zero dependencies
- **Server:** Ubuntu 22.04 ARM64 EC2 instance (`haproxy` / `34.204.39.160`)
- **Reverse proxy:** HAProxy with SSL termination (wildcard cert `*.tylerrbrown.com`)
- **App port:** 5050 (localhost only, accessed via HAProxy)
- **Service:** systemd `tictac.service`
- **Repo:** https://github.com/tylerrbrown/tictac-tracker

## URLs

- **Tic Tac:** `https://tictac.tylerrbrown.com/?k=x9f2k7m4-b8c1-e3a5-d6w0-q7r9s2t4u1v8`
- **Custom tracker:** `?k=SECRET&name=Gum&interval=7d`
- Access key param `?k=` required (shows "404" without it)

### URL Parameters

| Param | Default | Description |
|-------|---------|-------------|
| `k` | (required) | Access key |
| `name` | `Tic Tac` | Tracker name — displayed in UI, used as DB scope |
| `interval` | `3.5d` | Timer duration — supports `w` (weeks), `d` (days), `h` (hours), `m` (minutes) |

### Example URLs

- Tic Tac (default): `?k=SECRET`
- Gum weekly: `?k=SECRET&name=Gum&interval=1w`
- Vitamins daily: `?k=SECRET&name=Vitamins&interval=1d`

## App Logic

- Generic interval tracker — name and duration configurable via URL params
- Each tracker name gets its own isolated entries in the DB (`tracker` column)
- **Green** (ready): elapsed >= interval — show "take it" button
- **Red** (wait): elapsed < interval — show live countdown
- Button logs a new entry (server generates timestamp) and resets the timer
- Running history log at the bottom with delete capability

## API Endpoints

- `GET /` — serves `index.html`
- `GET /api/entries?name=X` — list entries for tracker X (JSON array of `{id, ts}`)
- `POST /api/entries?name=X` — add new entry for tracker X (returns `{id, ts}`)
- `PUT /api/entries/<id>` — update entry timestamp (body: `{"ts": <epoch_ms>}`)
- `DELETE /api/entries/<id>` — delete an entry

All API endpoints require `?k=SECRET`. The `name` param defaults to `tictac` if omitted (backward compatible).

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

## Decisions

- No auth/login — single user, obscure URL key is sufficient
- Zero Python dependencies — uses stdlib `http.server` + `sqlite3`
- SQLite DB stored at `/opt/tictac-tracker/tictac.db`
- GitHub Pages deployment abandoned (CORS issues with external DB services)
