"""
alerts.py — AlertManager
Отслеживает пороги метрик и отправляет Windows-уведомления через pystray/winotify.

Логика:
  - Каждый тик движка передаёт сюда свежий снимок данных через check(data)
  - AlertManager проверяет каждый настроенный триггер
  - Sustained-триггеры (cpu_load) срабатывают только если условие держится N секунд
  - Антиспам: повторное уведомление одного триггера — не раньше чем через cooldown секунд
  - Все сработавшие алёрты логируются в БД через db.log_alert()
"""

import time
import threading
from typing import Callable

from config import cfg


# ── Попытка импорта winotify (Windows toast-уведомления) ─────────────────

try:
    from winotify import Notification, audio
    _WINOTIFY = True
except ImportError:
    _WINOTIFY = False

# Fallback: уведомление через pystray icon (передаётся снаружи)
# Если ни то ни другое недоступно — просто print в лог


class AlertManager:
    """
    Проверяет метрики на превышение порогов и отправляет уведомления.

    Использование:
        alert_mgr = AlertManager(db_manager=db, notify_fn=icon.notify)
        # В цикле движка:
        alert_mgr.check(metrics_dict)
    """

    def __init__(self, db_manager=None, notify_fn: Callable | None = None):
        """
        db_manager  — DBManager для логирования алёртов (опционально)
        notify_fn   — callable(title, message) для отправки уведомлений через трей
                      если None — используется winotify или print
        """
        self.db        = db_manager
        self.notify_fn = notify_fn

        # ── Состояние sustained-триггеров ─────────────────────────────────
        # { trigger_key: timestamp когда условие впервые стало True }
        self._sustained_since: dict[str, float] = {}

        # ── Антиспам ──────────────────────────────────────────────────────
        # { trigger_key: timestamp последнего уведомления }
        self._last_fired: dict[str, float] = {}

        self._lock = threading.Lock()

    # ── Главный метод ─────────────────────────────────────────────────────

    def check(self, data: dict):
        """
        Вызывается из engine на каждом тике.
        Проверяет все настроенные триггеры и при необходимости отправляет уведомление.
        """
        thresholds = cfg.alert_thresholds
        now = time.time()

        checks = [
            ("cpu_load",     data.get("cpu_load", 0),     thresholds.get("cpu_load", {}),     "CPU",     "%"),
            ("ram_load",     data.get("ram_load", 0),      thresholds.get("ram_load", {}),     "RAM",     "%"),
            ("gpu_temp",     data.get("gpu_temp", 0),      thresholds.get("gpu_temp", {}),     "GPU",     "°C"),
            ("disk_usage",   data.get("disk_load", 0),     thresholds.get("disk_usage", {}),   "Disk",    "%"),
            ("net_download", data.get("net_download", 0),  thresholds.get("net_download", {}), "Network", "MB/s"),
        ]

        for key, value, threshold_cfg, label, unit in checks:
            self._evaluate(key, value, threshold_cfg, label, unit, now)

    # ── Внутренняя логика ─────────────────────────────────────────────────

    def _evaluate(
        self,
        key: str,
        value: float,
        threshold_cfg: dict,
        label: str,
        unit: str,
        now: float,
    ):
        critical      = threshold_cfg.get("critical", 999)
        warning       = threshold_cfg.get("warning",  999)
        sustained_sec = threshold_cfg.get("sustained_sec", 0)

        # Определяем уровень текущего значения
        if value >= critical:
            severity = "critical"
            threshold_hit = critical
        elif value >= warning:
            severity = "warning"
            threshold_hit = warning
        else:
            # Условие не выполнено — сбрасываем sustained-таймер
            self._sustained_since.pop(key, None)
            return

        fire_key = f"{key}_{severity}"

        # ── Sustained-проверка ────────────────────────────────────────────
        if sustained_sec > 0:
            with self._lock:
                if fire_key not in self._sustained_since:
                    self._sustained_since[fire_key] = now
                    return  # первый тик — начинаем отсчёт
                elif now - self._sustained_since[fire_key] < sustained_sec:
                    return  # ещё не набралось нужное время
                # Время набралось — падаем дальше к отправке
        else:
            # Без sustained — немедленно
            pass

        # ── Антиспам ─────────────────────────────────────────────────────
        cooldown = cfg.alert_cooldown_sec
        with self._lock:
            last = self._last_fired.get(fire_key, 0)
            if now - last < cooldown:
                return
            self._last_fired[fire_key] = now
            # Сбрасываем sustained после срабатывания
            self._sustained_since.pop(fire_key, None)

        # ── Формируем сообщение ───────────────────────────────────────────
        title, message = self._build_message(key, label, unit, value, severity)

        # ── Отправляем уведомление ────────────────────────────────────────
        self._send(title, message)

        # ── Логируем в БД ─────────────────────────────────────────────────
        if self.db:
            try:
                self.db.log_alert(trigger=fire_key, value=value, message=message)
            except Exception as e:
                print(f"[ALERT] DB log error: {e}")

    def _build_message(
        self, key: str, label: str, unit: str, value: float, severity: str
    ) -> tuple[str, str]:
        """Формирует заголовок и текст уведомления."""

        icon = "🔴" if severity == "critical" else "🟡"
        severity_word = "Критично" if severity == "critical" else "Внимание"

        templates = {
            "cpu_load":     (
                f"{icon} CPU — {severity_word}",
                f"Нагрузка процессора: {value:.0f}%. Проверьте активные процессы."
            ),
            "ram_load":     (
                f"{icon} RAM — {severity_word}",
                f"Занято памяти: {value:.0f}%. Возможно замедление системы."
            ),
            "gpu_temp":     (
                f"{icon} GPU Temp — {severity_word}",
                f"Температура видеокарты: {value:.0f}°C. Риск перегрева."
            ),
            "disk_usage":   (
                f"{icon} Диск — {severity_word}",
                f"Занято места на диске: {value:.0f}%. Освободите место."
            ),
            "net_download": (
                f"{icon} Сеть — {severity_word}",
                f"Высокая входящая нагрузка: {value:.1f} MB/s."
            ),
        }

        return templates.get(key, (f"{icon} {label} — {severity_word}", f"Значение: {value}{unit}"))

    def _send(self, title: str, message: str):
        """Отправляет уведомление доступным методом."""
        if self.notify_fn:
            try:
                self.notify_fn(title, message)
                return
            except Exception as e:
                print(f"[ALERT] notify_fn error: {e}")

        if _WINOTIFY:
            try:
                notif = Notification(
                    app_id="Wizor Pulse",
                    title=title,
                    msg=message,
                    duration="short",
                )
                notif.set_audio(audio.Default, loop=False)
                notif.show()
                return
            except Exception as e:
                print(f"[ALERT] winotify error: {e}")

        # Последний fallback
        print(f"[ALERT] {title}: {message}")