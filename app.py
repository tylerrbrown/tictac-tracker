#!/usr/bin/env python3
"""Tic Tac Tracker — zero-dependency Python HTTP server with SQLite."""

import json
import os
import sqlite3
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "tictac.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entries "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, ts BIGINT NOT NULL)"
    )
    conn.commit()
    return conn


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._serve_file("index.html", "text/html")
        elif self.path == "/api/entries":
            conn = get_db()
            rows = conn.execute("SELECT id, ts FROM entries ORDER BY ts ASC").fetchall()
            conn.close()
            self._json_response([{"id": r[0], "ts": r[1]} for r in rows])
        else:
            self._not_found()

    def do_POST(self):
        if self.path == "/api/entries":
            ts = int(time.time() * 1000)
            conn = get_db()
            cur = conn.execute("INSERT INTO entries (ts) VALUES (?)", (ts,))
            conn.commit()
            entry_id = cur.lastrowid
            conn.close()
            self._json_response({"id": entry_id, "ts": ts}, 201)
        else:
            self._not_found()

    def do_DELETE(self):
        if self.path.startswith("/api/entries/"):
            try:
                entry_id = int(self.path.split("/")[-1])
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

    def log_message(self, format, *args):
        pass  # silence request logs


if __name__ == "__main__":
    get_db()  # ensure table exists
    server = HTTPServer(("127.0.0.1", 5050), Handler)
    print("Tic Tac Tracker running on http://127.0.0.1:5050")
    server.serve_forever()
