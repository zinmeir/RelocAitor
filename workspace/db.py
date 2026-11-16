"""
workspace/db.py — storage for accounts and personal relocation workspaces (SQLite, standard library).

    RELOC_DB              path to the database file (default: instance/relocaitor.db)
    RELOC_ENCRYPTION_KEY  Fernet key for profile data at rest (default: generated once into
                          instance/encryption.key with owner-only permissions)

The profile (passport, income, savings, family, education…) is the sensitive part, so it is stored
encrypted. Emails are needed to sign in and are stored lowercased in plain text. Passwords are hashed
with scrypt. Session tokens are stored only as SHA-256 hashes. No document files are stored: the
checklist tracks what you have prepared, not the documents themselves.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, created TEXT NOT NULL,
  alerts_seen TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, data BLOB NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shortlist (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, country TEXT NOT NULL, note TEXT DEFAULT '',
  added TEXT NOT NULL, PRIMARY KEY (user_id, country)
);
CREATE TABLE IF NOT EXISTS saved_pathways (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, pathway_id TEXT NOT NULL, added TEXT NOT NULL,
  PRIMARY KEY (user_id, pathway_id)
);
CREATE TABLE IF NOT EXISTS checklist (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, route TEXT NOT NULL,
  item TEXT NOT NULL, basis TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, route TEXT NOT NULL,
  status TEXT NOT NULL, notes TEXT DEFAULT '', updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  user_id INTEGER, action TEXT NOT NULL, at TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("RELOC_DB") or ROOT / "instance" / "relocaitor.db")


def conn() -> sqlite3.Connection:
    path = str(db_path())
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "path", None) != path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.executescript(SCHEMA)
        _local.conn, _local.path = c, path
    return c


_fernet = None


def fernet() -> Fernet:
    global _fernet
    key = os.environ.get("RELOC_ENCRYPTION_KEY")
    if not key:
        kf = db_path().parent / "encryption.key"
        if not kf.exists():
            kf.parent.mkdir(parents=True, exist_ok=True)
            kf.write_bytes(Fernet.generate_key())
            os.chmod(kf, 0o600)
        key = kf.read_bytes().decode()
    if _fernet is None or getattr(_fernet, "_key_src", None) != key:
        _fernet = Fernet(_as_fernet_key(key))
        _fernet._key_src = key
    return _fernet


def _as_fernet_key(secret: str) -> bytes:
    """Accept a real Fernet key, or derive one from any long secret (platforms generate plain random strings)."""
    import base64
    import hashlib
    raw = secret.encode() if isinstance(secret, str) else secret
    try:
        if len(base64.urlsafe_b64decode(raw)) == 32:
            return raw
    except ValueError:
        pass
    if len(raw) < 32:
        raise RuntimeError("RELOC_ENCRYPTION_KEY must be a Fernet key or a random secret of at least 32 characters")
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def encrypt(obj) -> bytes:
    return fernet().encrypt(json.dumps(obj).encode())


def decrypt(blob: bytes):
    return json.loads(fernet().decrypt(blob).decode())
