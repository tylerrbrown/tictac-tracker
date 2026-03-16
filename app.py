#!/usr/bin/env python3
"""Tic Tac Tracker — zero-dependency Python HTTP server with SQLite + SSE."""

import csv
import io
import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "tictac.db")
SECRET = "x9f2k7m4-b8c1-e3a5-d6w0-q7r9s2t4u1v8"

# SSE clients: list of (wfile, lock) tuples
sse_clients = []
sse_lock = threading.Lock()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entries "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, ts BIGINT NOT NULL, "
        "tracker TEXT NOT NULL DEFAULT 'tictac')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS trackers "
        "(slug TEXT PRIMARY KEY, display_name TEXT NOT NULL, "
        "interval TEXT NOT NULL DEFAULT '3.5d', "
        "color TEXT NOT NULL DEFAULT 'orange')"
    )
    conn.commit()
    return conn


def seed_trackers(conn):
    """Auto-seed trackers table from existing entries."""
    rows = conn.execute(
        "SELECT DISTINCT tracker FROM entries"
    ).fetchall()
    for (slug,) in rows:
        existing = conn.execute(
            "SELECT 1 FROM trackers WHERE slug = ?", (slug,)
        ).fetchone()
        if not existing:
            display = slug.replace("-", " ").title()
            conn.execute(
                "INSERT INTO trackers (slug, display_name) VALUES (?, ?)",
                (slug, display)
            )
    conn.commit()


def slugify(name):
    return name.strip().lower().replace(" ", "-")


def broadcast_sse(event_type, data):
    """Send an SSE event to all connected clients."""
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    encoded = msg.encode()
    with sse_lock:
        dead = []
        for i, (wfile, lock) in enumerate(sse_clients):
            try:
                with lock:
                    wfile.write(encoded)
                    wfile.flush()
            except Exception:
                dead.append(i)
        for i in reversed(dead):
            sse_clients.pop(i)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _parse(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        return params

    def _check_key(self, params=None):
        if params is None:
            params = self._parse()
        if params.get("k", [None])[0] != SECRET:
            self._json_response({"error": "unauthorized"}, 401)
            return False
        return True

    def _tracker(self, params=None):
        if params is None:
            params = self._parse()
        return slugify(params.get("name", ["tictac"])[0])

    def _path_parts(self):
        """Return path without query string, split by /."""
        path = urlparse(self.path).path
        return [p for p in path.strip("/").split("/") if p]

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    # ── Routing ──────────────────────────────────────────────

    def do_GET(self):
        parts = self._path_parts()
        params = self._parse()

        # Static pages
        if not parts or (len(parts) == 0):
            self._serve_file("index.html", "text/html")
        elif parts == ["admin"]:
            if not self._check_key(params):
                return
            self._serve_file("admin.html", "text/html")

        # SSE stream
        elif parts == ["api", "events"]:
            self._handle_sse()

        # Tracker API
        elif parts == ["api", "trackers"]:
            self._get_trackers()
        elif len(parts) == 3 and parts[:2] == ["api", "tracker"]:
            self._get_tracker(parts[2])

        # Entry API (read)
        elif parts == ["api", "entries"]:
            tracker = self._tracker(params)
            self._get_entries(tracker)

        # Export
        elif len(parts) == 3 and parts[:2] == ["api", "export"]:
            if not self._check_key(params):
                return
            fmt = params.get("format", ["json"])[0]
            self._export_entries(parts[2], fmt)

        # Backup
        elif parts == ["api", "backup"]:
            if not self._check_key(params):
                return
            self._backup_db()

        else:
            self._not_found()

    def do_POST(self):
        parts = self._path_parts()
        params = self._parse()

        if parts == ["api", "entries"]:
            tracker = self._tracker(params)
            self._create_entry(tracker)

        elif parts == ["api", "trackers"]:
            self._create_tracker()

        elif parts == ["api", "restore"]:
            if not self._check_key(params):
                return
            self._restore_db()

        else:
            self._not_found()

    def do_PUT(self):
        parts = self._path_parts()
        params = self._parse()

        if len(parts) == 3 and parts[:2] == ["api", "entries"]:
            if not self._check_key(params):
                return
            self._update_entry(parts[2])

        elif len(parts) == 3 and parts[:2] == ["api", "trackers"]:
            if not self._check_key(params):
                return
            self._update_tracker(parts[2])

        else:
            self._not_found()

    def do_DELETE(self):
        parts = self._path_parts()
        params = self._parse()

        if len(parts) == 3 and parts[:2] == ["api", "entries"]:
            self._delete_entry(parts[2])

        elif parts == ["api", "entries"]:
            # Bulk delete all entries for a tracker
            if not self._check_key(params):
                return
            tracker = self._tracker(params)
            self._bulk_delete_entries(tracker)

        elif len(parts) == 3 and parts[:2] == ["api", "trackers"]:
            if not self._check_key(params):
                return
            self._delete_tracker(parts[2])

        else:
            self._not_found()

    # ── Entries ──────────────────────────────────────────────

    def _get_entries(self, tracker):
        conn = get_db()
        rows = conn.execute(
            "SELECT id, ts FROM entries WHERE tracker = ? ORDER BY ts ASC",
            (tracker,)
        ).fetchall()
        conn.close()
        self._json_response([{"id": r[0], "ts": r[1]} for r in rows])

    def _create_entry(self, tracker):
        ts = int(time.time() * 1000)
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO entries (ts, tracker) VALUES (?, ?)", (ts, tracker)
        )
        conn.commit()
        entry_id = cur.lastrowid
        conn.close()
        entry = {"id": entry_id, "ts": ts}
        self._json_response(entry, 201)
        broadcast_sse("entry-added", {"tracker": tracker, "entry": entry})

    def _update_entry(self, raw_id):
        try:
            entry_id = int(raw_id)
        except ValueError:
            self._not_found()
            return
        body = self._read_body()
        ts = body.get("ts")
        if not ts:
            self._json_response({"error": "ts required"}, 400)
            return
        conn = get_db()
        # Get tracker for this entry (for SSE broadcast)
        row = conn.execute(
            "SELECT tracker FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        tracker = row[0] if row else None
        conn.execute(
            "UPDATE entries SET ts = ? WHERE id = ?", (int(ts), entry_id)
        )
        conn.commit()
        conn.close()
        result = {"id": entry_id, "ts": int(ts)}
        self._json_response(result)
        if tracker:
            broadcast_sse("entry-updated", {"tracker": tracker, "entry": result})

    def _delete_entry(self, raw_id):
        try:
            entry_id = int(raw_id)
        except ValueError:
            self._not_found()
            return
        conn = get_db()
        row = conn.execute(
            "SELECT tracker FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        tracker = row[0] if row else None
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        conn.commit()
        conn.close()
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()
        if tracker:
            broadcast_sse("entry-deleted", {"tracker": tracker, "id": entry_id})

    def _bulk_delete_entries(self, tracker):
        conn = get_db()
        conn.execute("DELETE FROM entries WHERE tracker = ?", (tracker,))
        conn.commit()
        conn.close()
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()
        broadcast_sse("entries-cleared", {"tracker": tracker})

    # ── Trackers ─────────────────────────────────────────────

    def _get_trackers(self):
        conn = get_db()
        trackers = conn.execute(
            "SELECT slug, display_name, interval, color FROM trackers ORDER BY display_name"
        ).fetchall()
        # Get entry counts and last entry per tracker
        result = []
        for slug, display_name, interval, color in trackers:
            stats = conn.execute(
                "SELECT COUNT(*), MAX(ts) FROM entries WHERE tracker = ?",
                (slug,)
            ).fetchone()
            result.append({
                "slug": slug,
                "display_name": display_name,
                "interval": interval,
                "color": color,
                "entry_count": stats[0],
                "last_entry": stats[1],
            })
        conn.close()
        self._json_response(result)

    def _get_tracker(self, slug):
        conn = get_db()
        row = conn.execute(
            "SELECT slug, display_name, interval, color FROM trackers WHERE slug = ?",
            (slug,)
        ).fetchone()
        if not row:
            conn.close()
            self._json_response({"error": "not found"}, 404)
            return
        stats = conn.execute(
            "SELECT COUNT(*), MAX(ts) FROM entries WHERE tracker = ?",
            (slug,)
        ).fetchone()
        conn.close()
        self._json_response({
            "slug": row[0],
            "display_name": row[1],
            "interval": row[2],
            "color": row[3],
            "entry_count": stats[0],
            "last_entry": stats[1],
        })

    def _create_tracker(self):
        body = self._read_body()
        display_name = body.get("display_name", "").strip()
        if not display_name:
            self._json_response({"error": "display_name required"}, 400)
            return
        slug = slugify(display_name)
        interval = body.get("interval", "3.5d")
        color = body.get("color", "orange")
        conn = get_db()
        existing = conn.execute(
            "SELECT 1 FROM trackers WHERE slug = ?", (slug,)
        ).fetchone()
        if existing:
            conn.close()
            self._json_response({"error": "tracker already exists"}, 409)
            return
        conn.execute(
            "INSERT INTO trackers (slug, display_name, interval, color) VALUES (?, ?, ?, ?)",
            (slug, display_name, interval, color)
        )
        conn.commit()
        conn.close()
        tracker = {"slug": slug, "display_name": display_name,
                    "interval": interval, "color": color,
                    "entry_count": 0, "last_entry": None}
        self._json_response(tracker, 201)
        broadcast_sse("tracker-created", tracker)

    def _update_tracker(self, old_slug):
        body = self._read_body()
        conn = get_db()
        row = conn.execute(
            "SELECT slug, display_name, interval, color FROM trackers WHERE slug = ?",
            (old_slug,)
        ).fetchone()
        if not row:
            conn.close()
            self._json_response({"error": "not found"}, 404)
            return

        display_name = body.get("display_name", row[1]).strip()
        interval = body.get("interval", row[2])
        color = body.get("color", row[3])
        new_slug = slugify(display_name)

        if new_slug != old_slug:
            # Check for slug collision
            collision = conn.execute(
                "SELECT 1 FROM trackers WHERE slug = ?", (new_slug,)
            ).fetchone()
            if collision:
                conn.close()
                self._json_response({"error": "a tracker with that name already exists"}, 409)
                return
            # Rename: update entries and tracker in a transaction
            conn.execute("UPDATE entries SET tracker = ? WHERE tracker = ?",
                         (new_slug, old_slug))
            conn.execute("DELETE FROM trackers WHERE slug = ?", (old_slug,))
            conn.execute(
                "INSERT INTO trackers (slug, display_name, interval, color) VALUES (?, ?, ?, ?)",
                (new_slug, display_name, interval, color)
            )
        else:
            conn.execute(
                "UPDATE trackers SET display_name = ?, interval = ?, color = ? WHERE slug = ?",
                (display_name, interval, color, old_slug)
            )
        conn.commit()
        conn.close()
        result = {"slug": new_slug, "display_name": display_name,
                  "interval": interval, "color": color,
                  "old_slug": old_slug}
        self._json_response(result)
        broadcast_sse("tracker-updated", result)

    def _delete_tracker(self, slug):
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM trackers WHERE slug = ?", (slug,)
        ).fetchone()
        if not row:
            conn.close()
            self._json_response({"error": "not found"}, 404)
            return
        conn.execute("DELETE FROM entries WHERE tracker = ?", (slug,))
        conn.execute("DELETE FROM trackers WHERE slug = ?", (slug,))
        conn.commit()
        conn.close()
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()
        broadcast_sse("tracker-deleted", {"slug": slug})

    # ── SSE ──────────────────────────────────────────────────

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        lock = threading.Lock()
        client = (self.wfile, lock)
        with sse_lock:
            sse_clients.append(client)

        # Send initial heartbeat
        try:
            self.wfile.write(b": heartbeat\n\n")
            self.wfile.flush()
        except Exception:
            with sse_lock:
                if client in sse_clients:
                    sse_clients.remove(client)
            return

        # Keep connection alive with periodic heartbeats
        try:
            while True:
                time.sleep(30)
                with lock:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            with sse_lock:
                if client in sse_clients:
                    sse_clients.remove(client)

    # ── Export / Backup / Restore ────────────────────────────

    def _export_entries(self, slug, fmt):
        conn = get_db()
        rows = conn.execute(
            "SELECT id, ts FROM entries WHERE tracker = ? ORDER BY ts ASC",
            (slug,)
        ).fetchall()
        conn.close()

        if fmt == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "timestamp_ms", "date"])
            for r in rows:
                writer.writerow([r[0], r[1],
                                 time.strftime("%Y-%m-%d %H:%M:%S",
                                               time.localtime(r[1] / 1000))])
            body = output.getvalue().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{slug}-entries.csv"')
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            data = [{"id": r[0], "ts": r[1]} for r in rows]
            body = json.dumps(data, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{slug}-entries.json"')
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    def _backup_db(self):
        try:
            with open(DB_PATH, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition",
                             'attachment; filename="tictac-backup.db"')
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._json_response({"error": "database not found"}, 404)

    def _restore_db(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            self._json_response({"error": "no data"}, 400)
            return
        data = self.rfile.read(length)
        # Basic validation: SQLite files start with this header
        if not data[:16].startswith(b"SQLite format 3"):
            self._json_response({"error": "not a valid SQLite database"}, 400)
            return
        with open(DB_PATH, "wb") as f:
            f.write(data)
        self._json_response({"status": "restored"})
        broadcast_sse("db-restored", {})

    # ── Helpers ──────────────────────────────────────────────

    def _serve_file(self, filename, content_type):
        filepath = os.path.join(APP_DIR, filename)
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._not_found()

    def _json_response(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, format, *args):
        pass  # silence request logs


if __name__ == "__main__":
    conn = get_db()
    seed_trackers(conn)
    conn.close()
    server = ThreadingHTTPServer(("127.0.0.1", 5050), Handler)
    print("Tic Tac Tracker running on http://127.0.0.1:5050")
    server.serve_forever()
