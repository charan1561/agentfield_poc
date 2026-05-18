"""
HyperAgent Memory System — SQLite persistence for cross-run learning.

Tables:
  strategy_memory — what worked, indexed by embedding similarity
  anti_patterns   — what to avoid, tracked by frequency
  run_archive     — run history for similarity search
"""

import json
import os
import pickle
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from .retriever import _cosine

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "hyper_memory.db")


class HyperMemory:

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            c = self._conn.cursor()
            c.execute("PRAGMA journal_mode=WAL")

            c.execute("""
                CREATE TABLE IF NOT EXISTS strategy_memory (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type     TEXT    NOT NULL DEFAULT 'data_science',
                    failure_type  TEXT    NOT NULL DEFAULT 'none',
                    strategy_text TEXT    NOT NULL,
                    success_score REAL    DEFAULT 0.0,
                    usage_count   INTEGER DEFAULT 0,
                    embedding     BLOB,
                    created_at    REAL,
                    updated_at    REAL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS anti_patterns (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    failure_type TEXT    NOT NULL,
                    pattern_text TEXT    NOT NULL,
                    frequency    INTEGER DEFAULT 1,
                    created_at   REAL,
                    updated_at   REAL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS run_archive (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id            TEXT UNIQUE NOT NULL,
                    query             TEXT NOT NULL,
                    files_used        TEXT DEFAULT '[]',
                    score             REAL DEFAULT 0.0,
                    iterations        INTEGER DEFAULT 0,
                    failure_type      TEXT DEFAULT 'none',
                    strategies_used   TEXT DEFAULT '[]',
                    did_strategy_help INTEGER DEFAULT 0,
                    query_embedding   BLOB,
                    created_at        REAL
                )
            """)
            self._conn.commit()

    # ------------------------------------------------------------------ #
    #  Strategy Memory                                                    #
    # ------------------------------------------------------------------ #

    def store_strategy(
        self,
        strategy_text: str,
        success_score: float,
        embedding: List[float],
        task_type: str = "data_science",
        failure_type: str = "none",
    ) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO strategy_memory "
                "(task_type, failure_type, strategy_text, success_score, "
                " embedding, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (task_type, failure_type, strategy_text, success_score,
                 pickle.dumps(embedding), now, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def retrieve_similar_strategies(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        min_score: float = 0.3,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, task_type, failure_type, strategy_text, "
                "success_score, usage_count, embedding "
                "FROM strategy_memory"
            ).fetchall()

        hits: List[Dict[str, Any]] = []
        for r in rows:
            emb = pickle.loads(r["embedding"]) if r["embedding"] else None
            if emb is None:
                continue
            sim = _cosine(query_embedding, emb)
            if sim >= min_score:
                hits.append({
                    "id":            r["id"],
                    "task_type":     r["task_type"],
                    "failure_type":  r["failure_type"],
                    "strategy_text": r["strategy_text"],
                    "success_score": r["success_score"],
                    "usage_count":   r["usage_count"],
                    "similarity":    sim,
                })
        hits.sort(key=lambda h: h["similarity"], reverse=True)
        return hits[:top_k]

    def increment_usage(self, strategy_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE strategy_memory "
                "SET usage_count = usage_count + 1, updated_at = ? "
                "WHERE id = ?",
                (time.time(), strategy_id),
            )
            self._conn.commit()

    def update_strategy_score(self, strategy_id: int, new_score: float) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE strategy_memory "
                "SET success_score = ?, updated_at = ? WHERE id = ?",
                (new_score, time.time(), strategy_id),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    #  Anti-Patterns                                                      #
    # ------------------------------------------------------------------ #

    def store_anti_pattern(self, failure_type: str, pattern_text: str) -> int:
        now = time.time()
        with self._lock:
            dup = self._conn.execute(
                "SELECT id FROM anti_patterns "
                "WHERE failure_type = ? AND pattern_text = ?",
                (failure_type, pattern_text),
            ).fetchone()

            if dup:
                self._conn.execute(
                    "UPDATE anti_patterns "
                    "SET frequency = frequency + 1, updated_at = ? "
                    "WHERE id = ?",
                    (now, dup["id"]),
                )
                self._conn.commit()
                return dup["id"]

            cur = self._conn.execute(
                "INSERT INTO anti_patterns "
                "(failure_type, pattern_text, created_at, updated_at) "
                "VALUES (?,?,?,?)",
                (failure_type, pattern_text, now, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_anti_patterns(
        self, failure_type: Optional[str] = None, top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            if failure_type:
                rows = self._conn.execute(
                    "SELECT id, failure_type, pattern_text, frequency "
                    "FROM anti_patterns WHERE failure_type = ? "
                    "ORDER BY frequency DESC LIMIT ?",
                    (failure_type, top_k),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, failure_type, pattern_text, frequency "
                    "FROM anti_patterns "
                    "ORDER BY frequency DESC LIMIT ?",
                    (top_k,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Run Archive                                                        #
    # ------------------------------------------------------------------ #

    def store_run(
        self,
        run_id: str,
        query: str,
        files_used: List[str],
        score: float,
        iterations: int,
        failure_type: str = "none",
        strategies_used: Optional[List[str]] = None,
        did_strategy_help: bool = False,
        query_embedding: Optional[List[float]] = None,
    ) -> None:
        now = time.time()
        emb_blob = pickle.dumps(query_embedding) if query_embedding else None
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO run_archive "
                "(run_id, query, files_used, score, iterations, "
                " failure_type, strategies_used, did_strategy_help, "
                " query_embedding, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, query, json.dumps(files_used),
                    score, iterations, failure_type,
                    json.dumps(strategies_used or []),
                    1 if did_strategy_help else 0,
                    emb_blob, now,
                ),
            )
            self._conn.commit()

    def get_similar_runs(
        self, query_embedding: List[float], top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, query, files_used, score, iterations, "
                "failure_type, strategies_used, did_strategy_help, "
                "query_embedding FROM run_archive"
            ).fetchall()

        hits: List[Dict[str, Any]] = []
        for r in rows:
            emb = pickle.loads(r["query_embedding"]) if r["query_embedding"] else None
            if emb is None:
                continue
            sim = _cosine(query_embedding, emb)
            hits.append({
                "run_id":            r["run_id"],
                "query":             r["query"],
                "files_used":        json.loads(r["files_used"]),
                "score":             r["score"],
                "iterations":        r["iterations"],
                "failure_type":      r["failure_type"],
                "strategies_used":   json.loads(r["strategies_used"]),
                "did_strategy_help": bool(r["did_strategy_help"]),
                "similarity":        sim,
            })
        hits.sort(key=lambda h: h["similarity"], reverse=True)
        return hits[:top_k]

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        with self._lock:
            self._conn.close()
