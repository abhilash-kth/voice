"""
SQLite-backed fallback adapter for Prisma Client.

Provides the exact interface required by app/repo.py and backend/app/main.py:
- Async CRUD operations (create, find_unique, find_first, find_many, update, delete, count)
- Automatic table initialization with schema-matching defaults
- Thread-safe serialization off the asyncio event loop
- Zero binary engine downloads; runs instantly in local/sandboxed environments.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("voice-agent-saas-sqlite-prisma")

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "app.db"


class PrismaError(Exception):
    """Base error matching prisma_client.errors.PrismaError."""
    pass


def _make_cuid(prefix: str = "c") -> str:
    return f"{prefix}{uuid.uuid4().hex[:24]}"


def _now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M")


class Record:
    """Base object providing dot-notation access to database model fields."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"


class User(Record):
    pass


class Agent(Record):
    pass


class Call(Record):
    pass


class Transaction(Record):
    pass


class TableManager:
    def __init__(
        self,
        db: SQLiteDB,
        table_name: str,
        model_cls: type,
        id_prefix: str,
        defaults: Dict[str, Any],
        bool_fields: Optional[set[str]] = None,
    ):
        self.db = db
        self.table_name = table_name
        self.model_cls = model_cls
        self.id_prefix = id_prefix
        self.defaults = defaults
        self.bool_fields = bool_fields or set()

    def _to_db_val(self, k: str, v: Any) -> Any:
        if k in self.bool_fields and isinstance(v, bool):
            return 1 if v else 0
        return v

    def _from_db_row(self, row: dict) -> dict:
        d = dict(row)
        for k in self.bool_fields:
            if k in d:
                d[k] = bool(d[k])
        return d

    def _build_where(self, where: Optional[Dict[str, Any]]) -> tuple[str, list[Any]]:
        if not where:
            return "", []
        clauses = []
        params = []
        for k, v in where.items():
            if isinstance(v, dict) and "contains" in v:
                clauses.append(f"{k} LIKE ?")
                params.append(f"%{v['contains']}%")
            else:
                clauses.append(f"{k} = ?")
                params.append(self._to_db_val(k, v))
        return "WHERE " + " AND ".join(clauses), params

    def _create_sync(self, data: Dict[str, Any]) -> Any:
        row = dict(self.defaults)
        row.update(data)
        if "id" not in row or not row["id"]:
            row["id"] = _make_cuid(self.id_prefix)
        cols = list(row.keys())
        col_list = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))
        vals = [self._to_db_val(c, row[c]) for c in cols]
        sql = f"INSERT INTO {self.table_name} ({col_list}) VALUES ({placeholders})"
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(sql, vals)
            self.db.conn.commit()
            cur.execute(f"SELECT * FROM {self.table_name} WHERE id = ? LIMIT 1", (row["id"],))
            created_row = cur.fetchone()
        return self.model_cls(**self._from_db_row(dict(created_row)))

    async def create(self, data: Dict[str, Any]) -> Any:
        return await asyncio.to_thread(self._create_sync, data)

    def _find_first_sync(self, where: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        w_clause, params = self._build_where(where)
        sql = f"SELECT * FROM {self.table_name} {w_clause} LIMIT 1".strip()
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
        if not row:
            return None
        return self.model_cls(**self._from_db_row(dict(row)))

    async def find_first(self, where: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        return await asyncio.to_thread(self._find_first_sync, where)

    async def find_unique(self, where: Dict[str, Any]) -> Optional[Any]:
        return await asyncio.to_thread(self._find_first_sync, where)

    def _find_many_sync(
        self,
        where: Optional[Dict[str, Any]] = None,
        order: Optional[Dict[str, str]] = None,
        take: Optional[int] = None,
    ) -> List[Any]:
        w_clause, params = self._build_where(where)
        o_clause = ""
        if order:
            parts = [
                f"{k} {'DESC' if str(v).lower() == 'desc' else 'ASC'}"
                for k, v in order.items()
            ]
            o_clause = "ORDER BY " + ", ".join(parts)
        limit_clause = f"LIMIT {int(take)}" if take is not None else ""
        sql = f"SELECT * FROM {self.table_name} {w_clause} {o_clause} {limit_clause}".strip()
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [self.model_cls(**self._from_db_row(dict(r))) for r in rows]

    async def find_many(
        self,
        where: Optional[Dict[str, Any]] = None,
        order: Optional[Dict[str, str]] = None,
        take: Optional[int] = None,
    ) -> List[Any]:
        return await asyncio.to_thread(self._find_many_sync, where, order, take)

    def _update_sync(self, where: Dict[str, Any], data: Dict[str, Any]) -> Optional[Any]:
        existing = self._find_first_sync(where)
        if not existing:
            return None
        set_clauses = [f"{k} = ?" for k in data.keys()]
        set_vals = [self._to_db_val(k, v) for k, v in data.items()]
        w_clause, w_params = self._build_where(where)
        sql = f"UPDATE {self.table_name} SET {', '.join(set_clauses)} {w_clause}"
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(sql, set_vals + w_params)
            self.db.conn.commit()
            cur.execute(f"SELECT * FROM {self.table_name} WHERE id = ? LIMIT 1", (existing.id,))
            updated_row = cur.fetchone()
        return self.model_cls(**self._from_db_row(dict(updated_row)))

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Optional[Any]:
        return await asyncio.to_thread(self._update_sync, where, data)

    def _delete_sync(self, where: Dict[str, Any]) -> Optional[Any]:
        existing = self._find_first_sync(where)
        if not existing:
            return None
        w_clause, w_params = self._build_where(where)
        sql = f"DELETE FROM {self.table_name} {w_clause}"
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(sql, w_params)
            self.db.conn.commit()
        return existing

    async def delete(self, where: Dict[str, Any]) -> Optional[Any]:
        return await asyncio.to_thread(self._delete_sync, where)

    def _count_sync(self, where: Optional[Dict[str, Any]] = None) -> int:
        w_clause, params = self._build_where(where)
        sql = f"SELECT COUNT(*) FROM {self.table_name} {w_clause}".strip()
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
        return row[0] if row else 0

    async def count(self, where: Optional[Dict[str, Any]] = None) -> int:
        return await asyncio.to_thread(self._count_sync, where)


class SQLiteDB:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connected = False

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._init_conn()
        return self._conn

    def _init_conn(self) -> None:
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT DEFAULT '',
                passwordHash TEXT NOT NULL,
                walletBalance REAL DEFAULT 0.0,
                createdAt TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                userId TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                greeting TEXT DEFAULT '',
                language TEXT DEFAULT 'hi',
                gender TEXT DEFAULT 'female',
                voicePersonality TEXT DEFAULT 'friendly',
                clientRatePerMin REAL DEFAULT 2.5,
                memoryEnabled INTEGER DEFAULT 1,
                recordingEnabled INTEGER DEFAULT 1,
                maxConcurrency INTEGER DEFAULT 1,
                enabled INTEGER DEFAULT 1,
                agentMode TEXT DEFAULT 'assistant',
                announceText TEXT DEFAULT '',
                fallbackResponse TEXT DEFAULT 'Sorry, there is a temporary technical problem. Please try again shortly.',
                noResponseTimeoutSeconds INTEGER DEFAULT 60,
                noResponseMessage TEXT DEFAULT 'I did not hear a response, so I will end the call now. Thank you for calling.',
                providers TEXT DEFAULT '{}',
                knowledge TEXT DEFAULT '{}',
                createdAt TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                userId TEXT NOT NULL,
                agentId TEXT NOT NULL,
                mode TEXT DEFAULT 'browser',
                room TEXT DEFAULT '',
                phone TEXT,
                status TEXT DEFAULT 'planned',
                startedAt TEXT DEFAULT '',
                endedAt TEXT DEFAULT '',
                durationSeconds INTEGER DEFAULT 0,
                transcripts TEXT DEFAULT '[]',
                recordingUrl TEXT,
                usage TEXT DEFAULT '{}',
                cost TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                userId TEXT NOT NULL,
                kind TEXT DEFAULT '',
                amount REAL DEFAULT 0.0,
                note TEXT DEFAULT '',
                ts TEXT DEFAULT ''
            );
            """
        )


class Prisma:
    """Async Prisma Client replacement backed by SQLite."""

    def __init__(self, db_path: Path = DB_PATH):
        self._db = SQLiteDB(db_path)
        self._connected = False

        self.user = TableManager(
            db=self._db,
            table_name="users",
            model_cls=User,
            id_prefix="u_",
            defaults={"name": "", "walletBalance": 0.0, "createdAt": _now_str()},
        )
        self.agent = TableManager(
            db=self._db,
            table_name="agents",
            model_cls=Agent,
            id_prefix="a_",
            defaults={
                "description": "",
                "greeting": "",
                "language": "hi",
                "gender": "female",
                "voicePersonality": "friendly",
                "clientRatePerMin": 2.5,
                "memoryEnabled": True,
                "recordingEnabled": True,
                "maxConcurrency": 1,
                "enabled": True,
                "agentMode": "assistant",
                "announceText": "",
                "fallbackResponse": "Sorry, there is a temporary technical problem. Please try again shortly.",
                "noResponseTimeoutSeconds": 60,
                "noResponseMessage": "I did not hear a response, so I will end the call now. Thank you for calling.",
                "providers": "{}",
                "knowledge": "{}",
                "createdAt": _now_str(),
            },
            bool_fields={"memoryEnabled", "recordingEnabled", "enabled"},
        )
        self.call = TableManager(
            db=self._db,
            table_name="calls",
            model_cls=Call,
            id_prefix="c_",
            defaults={
                "mode": "browser",
                "room": "",
                "phone": None,
                "status": "planned",
                "startedAt": "",
                "endedAt": "",
                "durationSeconds": 0,
                "transcripts": "[]",
                "recordingUrl": None,
                "usage": "{}",
                "cost": "{}",
            },
        )
        self.transaction = TableManager(
            db=self._db,
            table_name="transactions",
            model_cls=Transaction,
            id_prefix="tx_",
            defaults={"kind": "", "amount": 0.0, "note": "", "ts": _now_str()},
        )

    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        def _sync_connect():
            with self._db.lock:
                _ = self._db.conn
        await asyncio.to_thread(_sync_connect)
        self._connected = True
        logger.info("SQLite Prisma adapter connected successfully")

    async def disconnect(self) -> None:
        def _sync_close():
            with self._db.lock:
                if self._db._conn:
                    try:
                        self._db._conn.close()
                    except Exception:
                        pass
                    self._db._conn = None
        await asyncio.to_thread(_sync_close)
        self._connected = False
