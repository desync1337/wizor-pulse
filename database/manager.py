"""
manager.py — DBManager
Управляет SQLite-базой данных: создаёт таблицы, пишет и читает данные.

Изменения по сравнению с оригиналом:
  - Добавлены таблицы: events, sessions, alerts_log
  - Добавлен метод save_event()
  - Добавлены методы для чтения истории (get_telemetry, get_events)
  - Автоочистка старых данных согласно cfg.data_retention_days
"""

import sqlite3
import json
from datetime import datetime, timedelta

from config import cfg


class DBManager:

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._create_tables()

    # ── Инициализация схемы ───────────────────────────────────────────────

    def _create_tables(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   DATETIME NOT NULL,
                    cpu_load    REAL, cpu_freq  REAL, cpu_temp  REAL, cpu_volt  REAL,
                    ram_load    REAL, ram_used_gb REAL, swap_load REAL,
                    gpu_load    REAL, gpu_temp  INT,  gpu_fan   INT,  gpu_vram_pct REAL,
                    bat_percent INT,  bat_charging INT,
                    disk_load   REAL, disk_read REAL, disk_write REAL,
                    net_download REAL, net_upload REAL,
                    top_processes TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp        DATETIME NOT NULL,
                    metric           TEXT NOT NULL,
                    value            REAL,
                    delta            REAL,
                    severity         TEXT,
                    culprit_process  TEXT,
                    culprit_pid      INT,
                    culprit_cpu_pct  REAL,
                    snapshot_procs   TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at DATETIME NOT NULL,
                    ended_at   DATETIME,
                    notes      TEXT
                );

                CREATE TABLE IF NOT EXISTS alerts_log (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    trigger   TEXT,
                    value     REAL,
                    message   TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(timestamp);
            """)

    # ── Запись данных ─────────────────────────────────────────────────────

    def save_metrics(self, data: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO telemetry (
                    timestamp, cpu_load, cpu_freq, cpu_temp, cpu_volt,
                    ram_load, ram_used_gb, swap_load,
                    gpu_load, gpu_temp, gpu_fan, gpu_vram_pct,
                    bat_percent, bat_charging,
                    disk_load, disk_read, disk_write,
                    net_download, net_upload, top_processes
                ) VALUES (
                    :timestamp, :cpu_load, :cpu_freq, :cpu_temp, :cpu_volt,
                    :ram_load, :ram_used_gb, :swap_load,
                    :gpu_load, :gpu_temp, :gpu_fan, :gpu_vram_pct,
                    :bat_percent, :bat_charging,
                    :disk_load, :disk_read, :disk_write,
                    :net_download, :net_upload, :top_procs
                )
            """, data)

    def save_event(self, event: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO events (
                    timestamp, metric, value, delta, severity,
                    culprit_process, culprit_pid, culprit_cpu_pct, snapshot_procs
                ) VALUES (
                    :timestamp, :metric, :value, :delta, :severity,
                    :culprit_process, :culprit_pid, :culprit_cpu_pct, :snapshot_procs
                )
            """, event)

    def log_alert(self, trigger: str, value: float, message: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO alerts_log (timestamp, trigger, value, message) VALUES (?, ?, ?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), trigger, value, message)
            )

    def start_session(self) -> int:
        """Создаёт новую запись сессии, возвращает её id."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sessions (started_at) VALUES (?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
            )
            return cur.lastrowid

    def end_session(self, session_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id)
            )

    # ── Чтение данных ─────────────────────────────────────────────────────

    def get_telemetry(self, hours: int = 1) -> list[dict]:
        """Возвращает записи телеметрии за последние N часов."""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM telemetry WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since,)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_events(self, hours: int = 24) -> list[dict]:
        """Возвращает события за последние N часов."""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM events WHERE timestamp >= ? ORDER BY timestamp DESC",
                (since,)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_metric_series(self, metric: str, hours: int = 1) -> list[tuple]:
        """
        Возвращает временной ряд одной метрики: [(timestamp_str, value), ...].
        Удобно для построения графиков.
        """
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            cur = conn.execute(
                f"SELECT timestamp, {metric} FROM telemetry WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since,)
            )
            return cur.fetchall()

    # ── Обслуживание БД ───────────────────────────────────────────────────

    def purge_old_data(self):
        """Удаляет данные старше cfg.data_retention_days дней."""
        cutoff = (datetime.now() - timedelta(days=cfg.data_retention_days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            for table in ("telemetry", "events", "alerts_log"):
                conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
        print(f"[DB] Purged data older than {cfg.data_retention_days} days.")

    # ── Внутренний хелпер ─────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Создаёт новое соединение (каждый поток — своё, как требует SQLite)."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")   # безопасно для многопоточной записи
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn