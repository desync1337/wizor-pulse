"""
hardware.py — HardwareCollector
Инкапсулирует всю логику сбора системных метрик.

Было: глобальные переменные, функции, фоновый поток на уровне модуля.
Стало: класс с явным жизненным циклом (start / collect / stop).
"""

import threading
import time
import json
import datetime
import psutil

# ── Опциональные тяжёлые библиотеки ───────────────────────────────────────

try:
    import pynvml
    pynvml.nvmlInit()
    _NV_ENABLED = True
except Exception:
    _NV_ENABLED = False

try:
    import wmi as _wmi_module
    _WMI_OBJ = _wmi_module.WMI()
    _WMI_ENABLED = True
except Exception:
    _WMI_OBJ = None
    _WMI_ENABLED = False


class HardwareCollector:
    """
    Собирает системные метрики.

    Внутри держит два фоновых потока:
      - _net_thread:   обновляет скорость сети каждую секунду (нужен для точного расчёта)
      - _procs_thread: собирает топ-процессов каждые procs_interval секунд (тяжёлая операция)

    Основной метод collect() вызывается из SystemEngine и возвращает полный снимок метрик.
    """

    def __init__(self, procs_interval: int = 15):
        self.procs_interval = procs_interval

        # ── Кэш сети (обновляется фоновым потоком) ────────────────────────
        _counters = psutil.net_io_counters()
        self._net_lock = threading.Lock()
        self._last_recv: int = _counters.bytes_recv
        self._last_sent: int = _counters.bytes_sent
        self._last_net_time: float = time.time()
        self._net_dl: float = 0.0   # MB/s
        self._net_ul: float = 0.0   # MB/s

        # ── Кэш процессов (обновляется фоновым потоком) ───────────────────
        self._procs_lock = threading.Lock()
        self._top_procs_json: str = "[]"

        self._running = False
        self._threads: list[threading.Thread] = []

    # ── Жизненный цикл ────────────────────────────────────────────────────

    def start(self):
        """Запускает фоновые потоки сбора данных."""
        self._running = True

        net_t = threading.Thread(target=self._net_loop, daemon=True, name="WP-Net")
        procs_t = threading.Thread(target=self._procs_loop, daemon=True, name="WP-Procs")

        self._threads = [net_t, procs_t]
        for t in self._threads:
            t.start()

    def stop(self):
        """Останавливает фоновые потоки."""
        self._running = False

    # ── Публичный метод сбора метрик ──────────────────────────────────────

    def collect(self) -> dict:
        """
        Возвращает полный снимок метрик системы.
        Быстрая операция — сеть и процессы берутся из кэша.
        """
        gpu = self._get_gpu()
        battery = psutil.sensors_battery()

        with self._net_lock:
            dl, ul = self._net_dl, self._net_ul

        with self._procs_lock:
            top_procs = self._top_procs_json

        return {
            "timestamp":   datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cpu_load":    psutil.cpu_percent(),
            "cpu_freq":    round(psutil.cpu_freq().current, 0) if psutil.cpu_freq() else 0.0,
            "cpu_temp":    self._get_cpu_temp(),
            "ram_load":    psutil.virtual_memory().percent,
            "ram_used_gb": round(psutil.virtual_memory().used / (1024 ** 3), 2),
            "swap_load":   psutil.swap_memory().percent,
            "gpu_load":    gpu["load"],
            "gpu_temp":    gpu["temp"],
            "gpu_fan":     gpu["fan"],
            "gpu_vram_pct":gpu["vram_pct"],
            "bat_percent": battery.percent if battery else -1,
            "bat_charging":1 if (battery and battery.power_plugged) else 0,
            "disk_load":   psutil.disk_usage("/").percent,
            "disk_read":   round(psutil.disk_io_counters().read_bytes  / (1024 ** 2), 2) if psutil.disk_io_counters() else 0.0,
            "disk_write":  round(psutil.disk_io_counters().write_bytes / (1024 ** 2), 2) if psutil.disk_io_counters() else 0.0,
            "net_download":dl,
            "net_upload":  ul,
            "cpu_volt":    self._get_cpu_volt(),
            "top_procs":   top_procs,
        }

    # ── Фоновые потоки ────────────────────────────────────────────────────

    def _net_loop(self):
        """Обновляет скорость сети раз в секунду."""
        while self._running:
            try:
                now = time.time()
                counters = psutil.net_io_counters()
                elapsed = now - self._last_net_time
                if elapsed <= 0:
                    elapsed = 1.0

                dl = ((counters.bytes_recv - self._last_recv) / elapsed) / (1024 ** 2)
                ul = ((counters.bytes_sent - self._last_sent) / elapsed) / (1024 ** 2)

                with self._net_lock:
                    self._net_dl = round(max(dl, 0.0), 2)
                    self._net_ul = round(max(ul, 0.0), 2)
                    self._last_recv = counters.bytes_recv
                    self._last_sent = counters.bytes_sent
                    self._last_net_time = now
            except Exception as e:
                print(f"[HW] net_loop error: {e}")
            time.sleep(1.0)

    def _procs_loop(self):
        """Собирает топ-процессов с заданным интервалом."""
        while self._running:
            try:
                procs = []
                for proc in psutil.process_iter(["name", "cpu_percent", "memory_info", "pid"]):
                    try:
                        info = proc.info
                        _name = (info.get("name") or "").lower()
                        _ignored = ("system idle process", "idle", "system", "")
                        if info["cpu_percent"] is not None and info["cpu_percent"] > 0.1 and _name not in _ignored:
                            procs.append({
                                "name":    info["name"],
                                "pid":     info["pid"],
                                "cpu_pct": info["cpu_percent"],
                                "ram_mb":  round(info["memory_info"].rss / (1024 ** 2), 1)
                                           if info.get("memory_info") else 0.0,
                            })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                top = sorted(procs, key=lambda x: x["cpu_pct"], reverse=True)[:5]
                with self._procs_lock:
                    self._top_procs_json = json.dumps(top)

            except Exception as e:
                print(f"[HW] procs_loop error: {e}")
            time.sleep(self.procs_interval)

    # ── Приватные хелперы ─────────────────────────────────────────────────

    def _get_gpu(self) -> dict:
        """Возвращает метрики GPU. При недоступности NVML — нули."""
        if not _NV_ENABLED:
            return {"load": 0, "temp": 0, "fan": 0, "vram_pct": 0}
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util   = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp   = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            mem    = pynvml.nvmlDeviceGetMemoryInfo(handle)
            vram_pct = round(mem.used / mem.total * 100, 1) if mem.total > 0 else 0
            try:
                fan = pynvml.nvmlDeviceGetFanSpeed(handle)
            except pynvml.NVMLError:
                fan = 0
            return {"load": util.gpu, "temp": temp, "fan": fan, "vram_pct": vram_pct}
        except Exception:
            return {"load": 0, "temp": 0, "fan": 0, "vram_pct": 0}

    def _get_cpu_temp(self) -> float:
        """Температура CPU через psutil.sensors_temperatures() (если доступно)."""
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return 0.0
            # Ищем ключи в порядке приоритета
            for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                if key in temps:
                    entries = temps[key]
                    if entries:
                        return round(entries[0].current, 1)
            # Fallback: первый доступный датчик
            for entries in temps.values():
                if entries:
                    return round(entries[0].current, 1)
        except Exception:
            pass
        return 0.0

    def _get_cpu_volt(self) -> float:
        """Напряжение CPU через WMI (Windows only)."""
        if not _WMI_ENABLED:
            return 0.0
        try:
            for proc in _WMI_OBJ.Win32_Processor():
                if proc.CurrentVoltage:
                    return float(proc.CurrentVoltage) / 10.0
        except Exception:
            pass
        return 0.0