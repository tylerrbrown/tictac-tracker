#!/usr/bin/env python3
"""Tic Tac Tracker — zero-dependency Python HTTP server with SQLite."""

import json
import os
import sqlite3
import time
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "tictac.db")
SECRET = "x9f2k7m4-b8c1-e3a5-d6w0-q7r9s2t4u1v8"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entries "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, ts BIGINT NOT NULL, "
        "tracker TEXT NOT NULL DEFAULT 'tictac')"
    )
    conn.commit()
    return conn


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
            self._not_found()
            return False
        return True

    def _tracker(self, params=None):
        if params is None:
            params = self._parse()
        return params.get("name", ["tictac"])[0].lower().replace(" ", "-")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._serve_file("index.html", "text/html")
        elif self.path.startswith("/api/entries"):
            params = self._parse()
            if not self._check_key(params):
                return
            tracker = self._tracker(params)
            conn = get_db()
            rows = conn.execute(
                "SELECT id, ts FROM entries WHERE tracker = ? ORDER BY ts ASC",
                (tracker,)
            ).fetchall()
            conn.close()
            self._json_response([{"id": r[0], "ts": r[1]} for r in rows])
        else:
            self._not_found()

    def do_POST(self):
        if self.path.startswith("/api/entries"):
            params = self._parse()
            if not self._check_key(params):
                return
            tracker = self._tracker(params)
            ts = int(time.time() * 1000)
            conn = get_db()
            cur = conn.execute(
                "INSERT INTO entries (ts, tracker) VALUES (?, ?)", (ts, tracker)
            )
            conn.commit()
            entry_id = cur.lastrowid
            conn.close()
            self._json_response({"id": entry_id, "ts": ts}, 201)
        else:
            self._not_found()

    def do_PUT(self):
        if self.path.startswith("/api/entries/"):
            params = self._parse()
            if not self._check_key(params):
                return
            try:
                entry_id = int(self.path.split("/")[-1].split("?")[0])
            except ValueError:
                self._not_found()
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            ts = body.get("ts")
            if not ts:
                self._json_response({"error": "ts required"}, 400)
                return
            conn = get_db()
            conn.execute("UPDATE entries SET ts = ? WHERE id = ?", (int(ts), entry_id))
            conn.commit()
            conn.close()
            self._json_response({"id": entry_id, "ts": int(ts)})
        else:
            self._not_found()

    def do_DELETE(self):
        if self.path.startswith("/api/entries/"):
            params = self._parse()
            if not self._check_key(params):
                return
            try:
                entry_id = int(self.path.split("/")[-1].split("?")[0])
            except ValueError:
                self._not_found()
                return
            conn = get_db()
            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            conn.commit()
            conn.close()
            self.send_response(204)
            self.end_headers()
        else:
            self._not_found()

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
        self.end_headers()

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, format, *args):
        pass  # silence request logs


if __name__ == "__main__":
    get_db()  # ensure table exists
    server = ThreadingHTTPServer(("127.0.0.1", 5050), Handler)
    print("Tic Tac Tracker running on http://127.0.0.1:5050")
    server.serve_forever()
