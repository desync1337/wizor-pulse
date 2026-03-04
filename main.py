"""
main.py — Точка входа Wizor Pulse
"""

import os
import threading

from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

from config import cfg
from ui.dashboard import MainDashboard
from database.manager import DBManager
from core.engine import SystemEngine


class TrayApp:

    def __init__(self):
        os.makedirs("logs", exist_ok=True)
        db_path = os.path.join("logs", "wizor_pulse.db")

        self.db     = DBManager(db_path)
        self.engine = SystemEngine(db_manager=self.db)
        self._session_id = self.db.start_session()

        self.root = MainDashboard(self.engine)
        self.root.protocol("WM_DELETE_WINDOW", self._hide_window)

        self.icon = None

    # ── Трей ──────────────────────────────────────────────────────────────

    def _make_tray_icon(self, state: str = "ok") -> Image.Image:
        colors = {
            "ok":       (46,  204, 113),   # зелёный
            "warning":  (243, 156,  18),   # жёлтый
            "critical": (231,  76,  60),   # красный
        }
        fill = colors.get(state, colors["ok"])
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        dc  = ImageDraw.Draw(img)
        dc.ellipse([4, 4, 60, 60], fill=fill)
        dc.ellipse([20, 20, 44, 44], fill=(255, 255, 255, 200))
        return img

    def _update_tray_icon(self):
        """Обновляет цвет иконки трея в зависимости от состояния системы."""
        if not self.icon:
            self.root.after(2000, self._update_tray_icon)
            return
        data = self.engine.last_data
        state = "ok"
        if data:
            thresholds = cfg.alert_thresholds
            checks = [
                (data.get("cpu_load",  0), thresholds.get("cpu_load",  {}).get("critical", 95)),
                (data.get("ram_load",  0), thresholds.get("ram_load",  {}).get("critical", 90)),
                (data.get("gpu_temp",  0), thresholds.get("gpu_temp",  {}).get("critical", 85)),
                (data.get("disk_load", 0), thresholds.get("disk_usage",{}).get("critical", 95)),
            ]
            warnings = [
                (data.get("cpu_load",  0), thresholds.get("cpu_load",  {}).get("warning", 80)),
                (data.get("ram_load",  0), thresholds.get("ram_load",  {}).get("warning", 80)),
                (data.get("gpu_temp",  0), thresholds.get("gpu_temp",  {}).get("warning", 80)),
            ]
            if any(v >= t for v, t in checks):
                state = "critical"
            elif any(v >= t for v, t in warnings):
                state = "warning"
        try:
            self.icon.icon = self._make_tray_icon(state)
        except Exception:
            pass
        self.root.after(3000, self._update_tray_icon)

    def _setup_tray(self):
        menu = pystray.Menu(
            item("Open Dashboard", self._show_window, default=True),
            item("Exit",           self._on_exit),
        )
        self.icon = pystray.Icon("WizorPulse", self._make_tray_icon(), "Wizor Pulse", menu)

        # Подключаем notify_fn к AlertManager после создания иконки
        self.engine.alerts.notify_fn = self.icon.notify

        self.icon.run()

    # ── Управление окном ──────────────────────────────────────────────────

    def _hide_window(self):
        self.root.withdraw()

    def _show_window(self, *_):
        self.root.deiconify()
        self.root.focus_force()

    def _on_exit(self, *_):
        print("[INFO] Завершение работы...")
        self.engine.stop()
        self.db.end_session(self._session_id)
        self.db.purge_old_data()
        if self.icon:
            self.icon.stop()
        self.root.quit()

    # ── Запуск ────────────────────────────────────────────────────────────

    def run(self):
        self.engine.start()

        tray_thread = threading.Thread(target=self._setup_tray, daemon=True, name="WP-Tray")
        tray_thread.start()

        if cfg.start_hidden:
            self.root.withdraw()

        self.root.after(3000, self._update_tray_icon)
        print("[OK] Wizor Pulse запущен.")
        self.root.mainloop()


if __name__ == "__main__":
    app = TrayApp()
    app.run()