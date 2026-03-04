"""
config.py — Централизованный конфиг Wizor Pulse.
Хранит все настройки и умеет сохранять/загружать их из JSON.
"""

import json
import os

# Путь к файлу настроек (рядом с main.py)
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "wizor_config.json")

# ── Значения по умолчанию ──────────────────────────────────────────────────

DEFAULTS = {
    # Движок сбора данных
    "collect_interval": 2,       # секунды между сбором метрик
    "db_write_interval": 5,      # секунды между записью в БД
    "procs_interval": 15,        # секунды между обновлением топ-процессов
    "data_retention_days": 30,   # сколько дней хранить данные в БД

    # UI
    "theme": "dark",             # "dark" | "light"
    "start_hidden": False,       # запускать свёрнутым в трей
    "start_with_windows": False, # добавить в автозапуск

    # Пороги алёртов (значения, при превышении которых срабатывает уведомление)
    "alert_thresholds": {
        "cpu_load":    {"warning": 80,  "critical": 95,  "sustained_sec": 30},
        "gpu_temp":    {"warning": 80,  "critical": 85,  "sustained_sec": 0},
        "ram_load":    {"warning": 80,  "critical": 90,  "sustained_sec": 0},
        "disk_usage":  {"warning": 90,  "critical": 95,  "sustained_sec": 0},
        "net_download":{"warning": 30,  "critical": 50,  "sustained_sec": 0},
    },

    # Антиспам алёртов: минимальный интервал между повторными уведомлениями одного типа
    "alert_cooldown_sec": 300,   # 5 минут

    # Event Correlation
    "spike_delta_threshold": 15, # минимальный прирост метрики (pp), чтобы считать его spike
    "event_log_max_memory": 200, # сколько событий держать в памяти (остальные — только в БД)
}


class Config:
    """
    Singleton-конфиг. Загружает настройки из JSON, мёрджит с дефолтами,
    предоставляет удобный доступ через атрибуты.

    Использование:
        from config import cfg
        interval = cfg.collect_interval
        cfg.collect_interval = 3
        cfg.save()
    """

    def __init__(self):
        self._data: dict = {}
        self.load()

    def load(self):
        """Загружает конфиг из файла. При отсутствии файла использует дефолты."""
        loaded = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[CONFIG] Не удалось загрузить {CONFIG_PATH}: {e}. Используются дефолты.")

        # Глубокий мёрдж: дефолты как основа, поверх — загруженные значения
        self._data = _deep_merge(DEFAULTS, loaded)

    def save(self):
        """Сохраняет текущие настройки в JSON-файл."""
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[CONFIG] Не удалось сохранить конфиг: {e}")

    def reset(self):
        """Сбрасывает все настройки к дефолтным значениям и сохраняет."""
        import copy
        self._data = copy.deepcopy(DEFAULTS)
        self.save()

    # ── Доступ к настройкам через атрибуты ────────────────────────────────

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"[CONFIG] Неизвестный параметр: '{name}'")

    def __setattr__(self, name: str, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def get(self, key: str, default=None):
        """Безопасное получение параметра с дефолтным значением."""
        return self._data.get(key, default)

    def as_dict(self) -> dict:
        """Возвращает копию всех настроек как словарь."""
        import copy
        return copy.deepcopy(self._data)


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Рекурсивный мёрдж двух словарей.
    override дополняет/перезаписывает base, но не удаляет ключи из base.
    """
    import copy
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ── Глобальный экземпляр ───────────────────────────────────────────────────
# Импортируй `cfg` в любом модуле:  from config import cfg
cfg = Config()