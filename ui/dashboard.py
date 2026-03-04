"""
dashboard.py — MainDashboard v2
Вкладки: Dashboard | History (заглушка) | System Info (заглушка) | Settings (заглушка)
Sparkline-графики на каждой карточке.
Полноценный Event Log внизу с цветовой маркировкой.
"""

import json
import collections
import tkinter as tk
import customtkinter as ctk

from config import cfg
from ui.history_view import HistoryView
from ui.sysinfo_view import SysInfoView
from ui.settings_view import SettingsView


# ─────────────────────────────────────────────────────────────────────────────
# Sparkline — миниатюрный Canvas-график
# ─────────────────────────────────────────────────────────────────────────────

class Sparkline:
    """
    Sparkline через tk.Canvas, создаётся явно через tk.Canvas(master).
    Не наследуется — обходит конфликт CTkFrame с width/height аргументами.
    """

    COLOR_OK       = "#2ecc71"
    COLOR_WARNING  = "#f39c12"
    COLOR_CRITICAL = "#e74c3c"
    BG             = "#1a1a2e"

    def __init__(self, master, width=160, height=36, maxlen=60, max_val=100):
        self._w       = width
        self._h       = height
        self._max_val = max_val
        self._data    = collections.deque([0.0] * maxlen, maxlen=maxlen)
        # Создаём Canvas напрямую без наследования
        self.widget = tk.Canvas(
            master,
            width=width, height=height,
            bg=self.BG, highlightthickness=0, bd=0
        )

    def pack(self, **kwargs):
        self.widget.pack(**kwargs)

    def push(self, value: float, color: str | None = None):
        self._data.append(float(value))
        self._draw(color)

    def _draw(self, color: str | None):
        self.widget.delete("all")
        vals = list(self._data)
        n    = len(vals)
        if n < 2:
            return

        top  = self._max_val or max(vals) or 1.0
        pts  = []
        step = self._w / (n - 1)

        for i, v in enumerate(vals):
            x = i * step
            y = self._h - (v / top) * (self._h - 4) - 2
            pts.extend([x, y])

        if color is None:
            last_frac = vals[-1] / top
            if last_frac >= 0.9:
                color = self.COLOR_CRITICAL
            elif last_frac >= 0.75:
                color = self.COLOR_WARNING
            else:
                color = self.COLOR_OK

        self.widget.create_line(*pts, fill=color, width=1.5, smooth=True)


# ─────────────────────────────────────────────────────────────────────────────
# MetricCard v2 — карточка + sparkline
# ─────────────────────────────────────────────────────────────────────────────

class MetricCard(ctk.CTkFrame):

    COLOR_OK       = "#2ecc71"
    COLOR_WARNING  = "#f39c12"
    COLOR_CRITICAL = "#e74c3c"

    def __init__(self, master, title: str, unit: str = "%",
                 max_val: float = 100, spark_maxlen: int = 60, **kwargs):
        super().__init__(master, **kwargs)
        self._unit    = unit
        self._max_val = max_val

        self.title_label = ctk.CTkLabel(
            self, text=title, font=("Roboto", 12, "bold"), text_color="#888888"
        )
        self.title_label.pack(pady=(10, 0), padx=14, anchor="w")

        self.value_label = ctk.CTkLabel(
            self, text="—", font=("Roboto", 28, "bold"), text_color=self.COLOR_OK
        )
        self.value_label.pack(pady=(2, 0), padx=14, anchor="w")

        self.spark = Sparkline(self, width=170, height=34, maxlen=spark_maxlen, max_val=max_val)
        self.spark.pack(pady=(4, 10), padx=10)

    def update_value(self, value: float | str, raw_fraction: float | None = None):
        if isinstance(value, str):
            self.value_label.configure(text=value)
            fraction = raw_fraction or 0.0
            self.spark.push(fraction * self._max_val)
        else:
            self.value_label.configure(text=f"{value}{self._unit}")
            fraction = raw_fraction if raw_fraction is not None else min(value / self._max_val, 1.0)
            self.spark.push(value)

        if fraction >= 0.9:
            color = self.COLOR_CRITICAL
        elif fraction >= 0.75:
            color = self.COLOR_WARNING
        else:
            color = self.COLOR_OK

        self.value_label.configure(text_color=color)


# ─────────────────────────────────────────────────────────────────────────────
# EventLogPanel v2
# ─────────────────────────────────────────────────────────────────────────────

class EventLogPanel(ctk.CTkFrame):
    """
    Лента событий с цветовой маркировкой по severity.
    critical → красный, warning → жёлтый, info → серый.
    """

    MAX_LINES = 120

    # Теги цветов для CTkTextbox (используем underlying tk.Text)
    TAG_CRITICAL = "crit"
    TAG_WARNING  = "warn"
    TAG_INFO     = "info"

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0d0d1a", corner_radius=8, **kwargs)

        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            header_row, text="EVENT LOG",
            font=("Roboto", 11, "bold"), text_color="#4a9eff"
        ).pack(side="left")

        self._btn_clear = ctk.CTkButton(
            header_row, text="Очистить", width=70, height=22,
            font=("Roboto", 10), fg_color="#1f2937", hover_color="#374151",
            command=self._clear
        )
        self._btn_clear.pack(side="right")

        # Используем tk.Text напрямую для поддержки цветных тегов
        self._text = tk.Text(
            self, height=7, font=("Courier", 10),
            bg="#0d0d1a", fg="#aaaaaa",
            insertbackground="#aaaaaa",
            relief="flat", state="disabled",
            selectbackground="#1f2937"
        )
        self._text.pack(fill="x", padx=8, pady=(0, 8))

        # Настраиваем теги цветов
        self._text.tag_configure(self.TAG_CRITICAL, foreground="#e74c3c")
        self._text.tag_configure(self.TAG_WARNING,  foreground="#f39c12")
        self._text.tag_configure(self.TAG_INFO,      foreground="#888888")

    def push_events(self, events: list[dict]):
        if not events:
            return

        self._text.configure(state="normal")
        for ev in events:
            line, tag = self._format_event(ev)
            self._text.insert("end", line, tag)

        # Обрезаем до MAX_LINES
        line_count = int(self._text.index("end-1c").split(".")[0])
        if line_count > self.MAX_LINES:
            self._text.delete("1.0", f"{line_count - self.MAX_LINES}.0")

        self._text.configure(state="disabled")
        self._text.see("end")

    def _format_event(self, ev: dict) -> tuple[str, str]:
        severity = ev.get("severity", "info")
        icon     = "●" if severity == "critical" else "◐" if severity == "warning" else "○"
        ts       = str(ev.get("timestamp", ""))[-8:]
        metric   = ev.get("metric", "").upper().replace("_LOAD", "").replace("_", " ")[:8]
        value    = ev.get("value", 0)
        delta    = ev.get("delta", 0)
        culprit  = ev.get("culprit_process") or "—"
        pid      = ev.get("culprit_pid") or ""
        pid_str  = f"[{pid}]" if pid else ""

        line = (
            f"  {ts}  {icon} {metric:<8}"
            f"  {value:>6.1f}"
            f"  Δ{delta:>+6.1f}"
            f"  →  {culprit} {pid_str}\n"
        )
        tag = self.TAG_CRITICAL if severity == "critical" else \
              self.TAG_WARNING  if severity == "warning"  else \
              self.TAG_INFO
        return line, tag

    def _clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
# TopProcessesWidget
# ─────────────────────────────────────────────────────────────────────────────

class TopProcessesWidget(ctk.CTkFrame):
    """Мини-таблица топ-5 процессов по CPU."""

    COLS = ("Process", "CPU%", "RAM MB")

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#111827", corner_radius=8, **kwargs)

        ctk.CTkLabel(
            self, text="TOP PROCESSES",
            font=("Roboto", 11, "bold"), text_color="#4a9eff"
        ).pack(anchor="w", padx=12, pady=(8, 4))

        # Заголовки
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=10)
        for col, w in zip(self.COLS, (140, 55, 70)):
            ctk.CTkLabel(
                hdr, text=col, font=("Roboto", 10, "bold"),
                text_color="#555555", width=w, anchor="w"
            ).pack(side="left", padx=2)

        # Строки (5 штук, переиспользуем labels)
        self._rows: list[list[ctk.CTkLabel]] = []
        for _ in range(5):
            row_frame = ctk.CTkFrame(self, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=1)
            labels = []
            for w in (140, 55, 70):
                lbl = ctk.CTkLabel(
                    row_frame, text="", font=("Courier", 10),
                    text_color="#888888", width=w, anchor="w"
                )
                lbl.pack(side="left", padx=2)
                labels.append(lbl)
            self._rows.append(labels)

        # Нижний отступ
        ctk.CTkLabel(self, text="").pack(pady=(0, 4))

    def update_procs(self, top_procs_json: str):
        try:
            procs: list[dict] = json.loads(top_procs_json)
        except Exception:
            procs = []

        for i, row_labels in enumerate(self._rows):
            if i < len(procs):
                p = procs[i]
                name    = p.get("name", "")[:18]
                cpu     = f"{p.get('cpu_pct', 0):.1f}%"
                ram     = f"{p.get('ram_mb', 0):.0f}"
                color   = "#e74c3c" if p.get("cpu_pct", 0) > 50 else \
                          "#f39c12" if p.get("cpu_pct", 0) > 20 else "#cccccc"
                row_labels[0].configure(text=name,  text_color=color)
                row_labels[1].configure(text=cpu,   text_color=color)
                row_labels[2].configure(text=ram,   text_color="#888888")
            else:
                for lbl in row_labels:
                    lbl.configure(text="")


# ─────────────────────────────────────────────────────────────────────────────
# Вкладки-заглушки (History / System Info / Settings)
# ─────────────────────────────────────────────────────────────────────────────

class PlaceholderTab(ctk.CTkFrame):
    def __init__(self, master, label: str, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(
            self, text=label,
            font=("Roboto", 20, "bold"), text_color="#333333"
        ).place(relx=0.5, rely=0.5, anchor="center")


# ─────────────────────────────────────────────────────────────────────────────
# MainDashboard
# ─────────────────────────────────────────────────────────────────────────────

class MainDashboard(ctk.CTk):

    NAV_ITEMS = ["Dashboard", "History", "System Info", "Settings"]

    def __init__(self, engine):
        super().__init__()
        self.engine = engine

        ctk.set_appearance_mode(cfg.theme)
        self.title("Wizor Pulse")
        self.geometry("1020x680")
        self.minsize(860, 580)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._active_tab = "Dashboard"
        self._nav_btns: dict[str, ctk.CTkButton] = {}
        self._tabs: dict[str, ctk.CTkFrame] = {}

        self._seen_event_count = 0
        self._ui_interval_ms = max(500, (cfg.collect_interval * 1000) // 2)

        self._build_sidebar()
        self._build_tabs()
        self._switch_tab("Dashboard")
        self._update_ui()

    # ── Sidebar ───────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=180, corner_radius=0, fg_color="#0d1117")
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar, text="WIZOR\nPULSE",
            font=("Roboto", 17, "bold"), text_color="#4a9eff", justify="center"
        ).pack(pady=(28, 2), padx=16)

        ctk.CTkLabel(
            sidebar, text="System Insight Analyzer",
            font=("Roboto", 9), text_color="#444"
        ).pack(pady=(0, 20))

        for label in self.NAV_ITEMS:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w",
                fg_color="transparent", hover_color="#161b22",
                text_color="#888888", font=("Roboto", 13),
                height=38, corner_radius=6,
                command=lambda l=label: self._switch_tab(l),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_btns[label] = btn

        # Версия внизу
        ctk.CTkLabel(
            sidebar, text="v0.2 — Этап 2",
            font=("Roboto", 9), text_color="#2a2a2a"
        ).pack(side="bottom", pady=10)

    # ── Вкладки ───────────────────────────────────────────────────────────

    def _build_tabs(self):
        self._tabs["Dashboard"]   = self._build_dashboard_tab()
        self._tabs["History"]     = HistoryView(self, db_manager=self.engine.db if hasattr(self.engine, "db") else None)
        self._tabs["System Info"] = SysInfoView(self)
        self._tabs["Settings"]    = SettingsView(self)

        for tab in self._tabs.values():
            tab.grid(row=0, column=1, sticky="nsew")

    def _build_dashboard_tab(self) -> ctk.CTkFrame:
        tab = ctk.CTkFrame(self, fg_color="#0d1117")
        tab.grid_columnconfigure((0, 1, 2), weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # ── Карточки метрик (2 ряда × 3 колонки) ─────────────────────────
        cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        cards_frame.grid(row=0, column=0, columnspan=3, padx=14, pady=(14, 6), sticky="nsew")
        cards_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.cards = {
            "cpu":  MetricCard(cards_frame, "CPU Load",   unit="%",   max_val=100),
            "gpu":  MetricCard(cards_frame, "GPU Load",   unit="%",   max_val=100),
            "ram":  MetricCard(cards_frame, "RAM Load",   unit="%",   max_val=100),
            "temp": MetricCard(cards_frame, "GPU Temp",   unit="°C",  max_val=110),
            "disk": MetricCard(cards_frame, "Disk Usage", unit="%",   max_val=100),
            "net":  MetricCard(cards_frame, "Network",    unit="",    max_val=100),
        }

        positions = [
            ("cpu", 0, 0), ("gpu", 0, 1), ("ram", 0, 2),
            ("temp",1, 0), ("disk",1, 1), ("net", 1, 2),
        ]
        for key, r, c in positions:
            self.cards[key].grid(row=r, column=c, padx=7, pady=5, sticky="nsew",
                                 in_=cards_frame)

        # ── Нижний ряд: Top Processes + Event Log ─────────────────────────
        bottom = ctk.CTkFrame(tab, fg_color="transparent")
        bottom.grid(row=1, column=0, columnspan=3, padx=14, pady=(0, 12), sticky="nsew")
        bottom.grid_columnconfigure(1, weight=1)

        self.top_procs = TopProcessesWidget(bottom)
        self.top_procs.grid(row=0, column=0, padx=(0, 8), sticky="nsew")

        self.event_log = EventLogPanel(bottom)
        self.event_log.grid(row=0, column=1, sticky="nsew")

        return tab

    def _switch_tab(self, label: str):
        # Скрываем все вкладки
        for tab in self._tabs.values():
            tab.grid_remove()

        # Показываем нужную
        self._tabs[label].grid()
        self._active_tab = label

        # Обновляем стили кнопок навигации
        for name, btn in self._nav_btns.items():
            if name == label:
                btn.configure(fg_color="#161b22", text_color="#4a9eff")
            else:
                btn.configure(fg_color="transparent", text_color="#888888")

    # ── Цикл обновления UI ────────────────────────────────────────────────

    def _update_ui(self):
        if self._active_tab == "Dashboard":
            self._refresh_dashboard()

        self.after(self._ui_interval_ms, self._update_ui)

    def _refresh_dashboard(self):
        data = self.engine.last_data
        if not data:
            return

        self.cards["cpu"].update_value(data.get("cpu_load", 0))
        self.cards["gpu"].update_value(data.get("gpu_load", 0))
        self.cards["ram"].update_value(data.get("ram_load", 0))
        self.cards["temp"].update_value(data.get("gpu_temp", 0))
        self.cards["disk"].update_value(data.get("disk_load", 0))

        dl = data.get("net_download", 0)
        ul = data.get("net_upload", 0)
        net_frac = min((dl + ul) / 100.0, 1.0)
        self.cards["net"].update_value(f"↓{dl}  ↑{ul}", raw_fraction=net_frac)

        self.top_procs.update_procs(data.get("top_procs", "[]"))

        # Event Log — только новые события
        events = self.engine.last_events
        new = events[self._seen_event_count:]
        if new:
            self.event_log.push_events(new)
            self._seen_event_count = len(events)