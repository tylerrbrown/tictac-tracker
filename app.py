#!/usr/bin/env python3
"""Tic Tac Tracker — tiny Flask app with SQLite backend."""

import os
import sqlite3
import time
from flask import Flask, jsonify, request, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "tictac.db")

app = Flask(__name__, static_folder=APP_DIR)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts BIGINT NOT NULL)"
    )
    conn.commit()
    return conn


@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.route("/api/entries", methods=["GET"])
def list_entries():
    conn = get_db()
    rows = conn.execute("SELECT id, ts FROM entries ORDER BY ts ASC").fetchall()
    conn.close()
    return jsonify([{"id": r[0], "ts": r[1]} for r in rows])


@app.route("/api/entries", methods=["POST"])
def add_entry():
    ts = int(time.time() * 1000)
    conn = get_db()
    cur = conn.execute("INSERT INTO entries (ts) VALUES (?)", (ts,))
    conn.commit()
    entry_id = cur.lastrowid
    conn.close()
    return jsonify({"id": entry_id, "ts": ts}), 201


@app.route("/api/entries/<int:entry_id>", methods=["DELETE"])
def delete_entry(entry_id):
    conn = get_db()
    conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return "", 204


if __name__ == "__main__":
    get_db()  # ensure table exists
    app.run(host="127.0.0.1", port=5050)
