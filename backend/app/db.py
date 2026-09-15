"""SQLite persistence layer for the irrigation changeover console."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get(
    "IRRIGATION_DB",
    str(Path(__file__).resolve().parent.parent / "irrigation.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('tank','junction','valve','outlet')),
  label TEXT NOT NULL DEFAULT '',
  x REAL NOT NULL,
  y REAL NOT NULL,
  elevation REAL NOT NULL DEFAULT 0,
  accessible_side TEXT NOT NULL DEFAULT 'S'
);
CREATE TABLE IF NOT EXISTS pipes (
  id TEXT PRIMARY KEY,
  from_node TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  to_node TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  capacity_l REAL NOT NULL DEFAULT 0,
  max_flow_lpm REAL NOT NULL DEFAULT 10,
  length_m REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS furrows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  outlet_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  tail_x REAL NOT NULL,
  tail_y REAL NOT NULL,
  tail_elevation REAL NOT NULL DEFAULT 0,
  wet_min_min REAL NOT NULL DEFAULT 3,
  wet_max_min REAL NOT NULL DEFAULT 10,
  state TEXT NOT NULL DEFAULT 'pending',
  opened_at TEXT,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS zones (
  id TEXT PRIMARY KEY,
  x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
  label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS fittings (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  hose_length_m REAL NOT NULL DEFAULT 0,
  count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  flow_lpm REAL NOT NULL DEFAULT 8,
  state_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS steps (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  type TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  warning TEXT,
  activated_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}'
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def jload(text: str, default):
    try:
        return json.loads(text)
    except Exception:
        return default
