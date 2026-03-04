"""
engine.py — SystemEngine
Оркестратор: запускает потоки сбора, записи в БД, корреляции событий и алёртов.
"""

import threading
import queue
import time

from config import cfg
from core.hardware import HardwareCollector
from core.alerts import AlertManager


class SystemEngine:
    """
    Потоки:
      WP-Collect — HardwareCollector.collect() → кэш + корреляция + алёрты → очередь
      WP-Write   — очередь → DBManager (telemetry + events)
    """

    def __init__(self, db_manager, interval: int | None = None):
        self.db       = db_manager
        self.interval = interval or cfg.collect_interval

        self.hardware = HardwareCollector(procs_interval=cfg.procs_interval)

        # AlertManager — notify_fn подключается снаружи после создания icon
        self.alerts = AlertManager(db_manager=self.db)

        # ── Thread-safe кэш последнего снимка ────────────────────────────
        self._data_lock  = threading.Lock()
        self._last_data: dict | None = None

        # ── Thread-safe кэш событий для Event Log ────────────────────────
        self._events_lock  = threading.Lock()
        self._last_events: list[dict] = []

        self._prev_data: dict | None = None

        self._data_queue: queue.Queue = queue.Queue()
        self.running = False

    # ── Публичные свойства ────────────────────────────────────────────────

    @property
    def last_data(self) -> dict | None:
        with self._data_lock:
            return self._last_data

    @property
    def last_events(self) -> list[dict]:
        with self._events_lock:
            return list(self._last_events)

    # ── Управление ────────────────────────────────────────────────────────

    def start(self):
        self.running = True
        self.hardware.start()
        threading.Thread(target=self._collect_loop, daemon=True, name="WP-Collect").start()
        threading.Thread(target=self._write_loop,   daemon=True, name="WP-Write").start()

    def stop(self):
        self.running = False
        self.hardware.stop()

    # ── Потоки ────────────────────────────────────────────────────────────

    def _collect_loop(self):
        while self.running:
            try:
                metrics = self.hardware.collect()

                with self._data_lock:
                    self._last_data = metrics

                events = self._correlate(metrics)
                if events:
                    with self._events_lock:
                        self._last_events.extend(events)
                        max_mem = cfg.event_log_max_memory
                        if len(self._last_events) > max_mem:
                            self._last_events = self._last_events[-max_mem:]

                # Алёрты — быстрая проверка порогов, не блокирует
                self.alerts.check(metrics)

                self._prev_data = metrics
                self._data_queue.put((metrics, events))

            except Exception as e:
                print(f"[ENGINE] collect error: {e}")

            time.sleep(self.interval)

    def _write_loop(self):
        while self.running:
            try:
                metrics, events = self._data_queue.get(timeout=1)
                self.db.save_metrics(metrics)
                for ev in events:
                    self.db.save_event(ev)
                self._data_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ENGINE] write error: {e}")

    # ── Event Correlation ─────────────────────────────────────────────────

    def _correlate(self, current: dict) -> list[dict]:
        if self._prev_data is None:
            return []

        threshold = cfg.spike_delta_threshold
        alert_cfg = cfg.alert_thresholds
        events    = []

        watched = {
            "cpu_load":    alert_cfg.get("cpu_load",    {}).get("critical", 95),
            "ram_load":    alert_cfg.get("ram_load",    {}).get("critical", 90),
            "gpu_temp":    alert_cfg.get("gpu_temp",    {}).get("critical", 85),
            "net_download":alert_cfg.get("net_download",{}).get("critical", 50),
        }

        for metric, critical_val in watched.items():
            curr_val = current.get(metric, 0)
            prev_val = self._prev_data.get(metric, 0)
            delta    = curr_val - prev_val

            warning_val = cfg.alert_thresholds.get(metric, {}).get("warning", critical_val * 0.85)
            if curr_val >= critical_val and delta >= threshold:
                severity = "critical"
            elif curr_val >= warning_val and delta >= threshold:
                severity = "warning"
            else:
                continue

            culprit = _find_culprit(current.get("top_procs", "[]"), metric)

            events.append({
                "timestamp":       current["timestamp"],
                "metric":          metric,
                "value":           curr_val,
                "delta":           round(delta, 2),
                "severity":        severity,
                "culprit_process": culprit.get("name"),
                "culprit_pid":     culprit.get("pid"),
                "culprit_cpu_pct": culprit.get("cpu_pct"),
                "snapshot_procs":  current.get("top_procs", "[]"),
            })

        return events


def _find_culprit(top_procs_json: str, metric: str) -> dict:
    import json
    try:
        procs: list[dict] = json.loads(top_procs_json)
    except Exception:
        return {}
    if not procs:
        return {}
    if metric == "ram_load":
        return max(procs, key=lambda p: p.get("ram_mb", 0), default={})
    return max(procs, key=lambda p: p.get("cpu_pct", 0), default={})