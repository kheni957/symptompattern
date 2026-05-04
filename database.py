import sqlite3
import json
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "healthwatch.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Projects table
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            description TEXT,
            keywords    TEXT,   -- JSON list
            sources     TEXT,   -- JSON list
            latency     TEXT    DEFAULT 'daily',
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
            active      INTEGER DEFAULT 1
        )
    """)

    # Posts / signals table
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id        INTEGER,
            date              TEXT,
            source            TEXT,
            title             TEXT,
            text              TEXT,
            url               TEXT,
            sentiment         TEXT,
            sentiment_score   REAL,
            risk_level        TEXT,
            risk_score        INTEGER,
            risk_reason       TEXT,
            entities          TEXT,   -- JSON
            pii_flagged       INTEGER DEFAULT 0,
            pii_details       TEXT,
            safety_flag       INTEGER DEFAULT 0,
            safety_reason     TEXT,
            confidence        REAL,
            fetched_at        TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)

    # Source engines registry
    c.execute("""
        CREATE TABLE IF NOT EXISTS source_engines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            engine_type TEXT,
            config      TEXT,   -- JSON
            active      INTEGER DEFAULT 1
        )
    """)

    # Seed default engines
    engines = [
        ("Reddit",  "api",     json.dumps({"base_url": "https://www.reddit.com", "requires_key": False})),
        ("OpenFDA", "api",     json.dumps({"base_url": "https://api.fda.gov",    "requires_key": False})),
        ("PubMed",  "api",     json.dumps({"base_url": "https://eutils.ncbi.nlm.nih.gov", "requires_key": False})),
        ("Twitter", "api",     json.dumps({"base_url": "https://api.twitterapi.io", "requires_key": True})),
    ]
    for name, etype, config in engines:
        c.execute("""
            INSERT OR IGNORE INTO source_engines (name, engine_type, config)
            VALUES (?, ?, ?)
        """, (name, etype, config))

    conn.commit()
    conn.close()

# ── Projects CRUD ────────────────────────────────────────────

def create_project(name, description, keywords, sources, latency="daily"):
    conn = get_conn()
    conn.execute("""
        INSERT INTO projects (name, description, keywords, sources, latency)
        VALUES (?, ?, ?, ?, ?)
    """, (name, description, json.dumps(keywords), json.dumps(sources), latency))
    conn.commit()
    conn.close()

def get_projects():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM projects WHERE active=1 ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_project(pid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_project(pid, name, description, keywords, sources, latency):
    conn = get_conn()
    conn.execute("""
        UPDATE projects SET name=?, description=?, keywords=?, sources=?, latency=?
        WHERE id=?
    """, (name, description, json.dumps(keywords), json.dumps(sources), latency, pid))
    conn.commit()
    conn.close()

def delete_project(pid):
    conn = get_conn()
    conn.execute("UPDATE projects SET active=0 WHERE id=?", (pid,))
    conn.commit()
    conn.close()

# ── Signals CRUD ─────────────────────────────────────────────

def save_signals(project_id, signals):
    conn = get_conn()
    for s in signals:
        conn.execute("""
            INSERT INTO signals (
                project_id, date, source, title, text, url,
                sentiment, sentiment_score, risk_level, risk_score,
                risk_reason, entities, pii_flagged, pii_details,
                safety_flag, safety_reason, confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            project_id,
            s.get("date"), s.get("source"), s.get("title"), s.get("text"), s.get("url"),
            s.get("sentiment"), s.get("sentiment_score"),
            s.get("risk_level"), s.get("risk_score"),
            s.get("risk_reason"), json.dumps(s.get("entities", [])),
            int(s.get("pii_flagged", 0)), s.get("pii_details", ""),
            int(s.get("safety_flag", 0)), s.get("safety_reason", ""),
            s.get("confidence", 0.0)
        ))
    conn.commit()
    conn.close()

def get_signals(project_id, limit=500):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM signals WHERE project_id=?
        ORDER BY fetched_at DESC LIMIT ?
    """, (project_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_source_engines():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM source_engines WHERE active=1").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_source_engine(name, engine_type, config):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO source_engines (name, engine_type, config)
        VALUES (?, ?, ?)
    """, (name, engine_type, json.dumps(config)))
    conn.commit()
    conn.close()