import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import VALID_PROVIDER_IDS, ProviderId, get_app_settings


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn():
    settings = get_app_settings()
    conn = _connect(settings.db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    settings = get_app_settings()
    with _connect(settings.db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL NOT NULL,
              provider TEXT NOT NULL,
              user_message TEXT NOT NULL,
              assistant_message TEXT NOT NULL,
              latency_ms INTEGER NOT NULL,
              ok INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_access_ts ON access_log(ts DESC);
            """
        )
        conn.commit()


def get_default_provider() -> ProviderId:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = 'default_provider'").fetchone()
        if row:
            v = row["value"]
            if v in VALID_PROVIDER_IDS:
                return v  # type: ignore[return-value]
    return get_app_settings().default_provider


def set_default_provider(provider: ProviderId) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO kv(key, value) VALUES('default_provider', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (provider,),
        )


def get_default_chat_preset() -> str:
    from app.models_yaml import get_preset_system

    with get_conn() as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = 'default_chat_preset'").fetchone()
        if row is not None:
            raw = row["value"]
            pid = raw.strip() if raw else ""
            if not pid:
                return ""
            if get_preset_system(pid):
                return pid
    env_default = get_app_settings().default_chat_preset.strip()
    if env_default and get_preset_system(env_default):
        return env_default
    return ""


def set_default_chat_preset(preset_id: str) -> None:
    from app.models_yaml import get_preset_system

    pid = preset_id.strip()
    if pid and not get_preset_system(pid):
        raise ValueError(f"未知的 preset: {pid}")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO kv(key, value) VALUES('default_chat_preset', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (pid,),
        )


def log_access(
    provider: ProviderId,
    user_message: str,
    assistant_message: str,
    latency_ms: int,
    ok: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO access_log(ts, provider, user_message, assistant_message, latency_ms, ok)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                provider,
                user_message[:4000],
                assistant_message[:8000],
                latency_ms,
                1 if ok else 0,
            ),
        )


def recent_records(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, ts, provider, user_message, assistant_message, latency_ms, ok
            FROM access_log ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    now = time.time()
    day_ago = now - 86400
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM access_log").fetchone()["c"]
        last_24h = conn.execute(
            "SELECT COUNT(*) AS c FROM access_log WHERE ts >= ?", (day_ago,)
        ).fetchone()["c"]
        by_provider = conn.execute(
            """
            SELECT provider, COUNT(*) AS c FROM access_log GROUP BY provider
            """
        ).fetchall()
    return {
        "total_requests": total,
        "last_24h_requests": last_24h,
        "by_provider": {r["provider"]: r["c"] for r in by_provider},
    }
