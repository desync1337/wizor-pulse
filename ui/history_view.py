"""
history_view.py — вкладка History
Интерактивные графики нагрузки с annotated markers событий.
Периоды: 1ч / 6ч / 24ч / 7 дней.
"""

import json
import tkinter as tk
import customtkinter as ctk
from datetime import datetime

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates


# Палитра метрик
METRIC_COLORS = {
    "cpu_load":    "#4a9eff",
    "ram_load":    "#2ecc71",
    "gpu_load":    "#e74c3c",
    "gpu_temp":    "#f39c12",
    "disk_load":   "#9b59b6",
    "net_download":"#1abc9c",
}

METRIC_LABELS = {
    "cpu_load":    "CPU %",
    "ram_load":    "RAM %",
    "gpu_load":    "GPU %",
    "gpu_temp":    "GPU °C",
    "disk_load":   "Disk %",
    "net_download":"Net ↓ MB/s",
}

SEVERITY_COLORS = {
    "critical": "#e74c3c",
    "warning":  "#f39c12",
}


class HistoryView(ctk.CTkFrame):
    """
    Вкладка History.
    Слева — чекбоксы выбора метрик и переключатель периода.
    Справа — matplotlib-график с annotated markers.
    """

    PERIODS = {"1ч": 1, "6ч": 6, "24ч": 24, "7д": 168}

    def __init__(self, master, db_manager, **kwargs):
        super().__init__(master, fg_color="#0d1117", **kwargs)
        self.db = db_manager
        self._period_hours = 1
        self._active_metrics: set[str] = {"cpu_load", "ram_load", "gpu_load"}
        self._show_markers = tk.BooleanVar(value=True)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_chart()
        self._build_sidebar()
        self.after(100, self.refresh)

    # ── Левая панель управления ───────────────────────────────────────────

    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=180, fg_color="#111827", corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)

        ctk.CTkLabel(
            side, text="ПЕРИОД",
            font=("Roboto", 10, "bold"), text_color="#555"
        ).pack(anchor="w", padx=14, pady=(16, 4))

        # Кнопки периода
        self._period_btns: dict[str, ctk.CTkButton] = {}
        btn_row = ctk.CTkFrame(side, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 14))
        for label in self.PERIODS:
            btn = ctk.CTkButton(
                btn_row, text=label, width=36, height=26,
                font=("Roboto", 11), corner_radius=4,
                fg_color="#1f2937", hover_color="#374151", text_color="#888",
                command=lambda l=label: self._set_period(l)
            )
            btn.pack(side="left", padx=2)
            self._period_btns[label] = btn
        self._set_period("1ч")  # активируем дефолт

        ctk.CTkLabel(
            side, text="МЕТРИКИ",
            font=("Roboto", 10, "bold"), text_color="#555"
        ).pack(anchor="w", padx=14, pady=(0, 4))

        # Чекбоксы метрик
        self._metric_vars: dict[str, tk.BooleanVar] = {}
        for key, label in METRIC_LABELS.items():
            var = tk.BooleanVar(value=(key in self._active_metrics))
            color = METRIC_COLORS.get(key, "#ffffff")
            row = ctk.CTkFrame(side, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            # Цветная точка
            dot = tk.Canvas(row, width=10, height=10, bg="#111827",
                            highlightthickness=0)
            dot.create_oval(1, 1, 9, 9, fill=color, outline="")
            dot.pack(side="left", padx=(4, 6))
            cb = ctk.CTkCheckBox(
                row, text=label, variable=var,
                font=("Roboto", 11), text_color="#aaa",
                fg_color="#4a9eff", hover_color="#1f2937",
                checkmark_color="#fff",
                command=lambda k=key, v=var: self._toggle_metric(k, v)
            )
            cb.pack(side="left")
            self._metric_vars[key] = var

        # Тогл маркеров
        ctk.CTkLabel(
            side, text="СОБЫТИЯ",
            font=("Roboto", 10, "bold"), text_color="#555"
        ).pack(anchor="w", padx=14, pady=(16, 4))

        ctk.CTkCheckBox(
            side, text="Показать маркеры",
            variable=self._show_markers,
            font=("Roboto", 11), text_color="#aaa",
            fg_color="#4a9eff", hover_color="#1f2937",
            checkmark_color="#fff",
            command=self.refresh
        ).pack(anchor="w", padx=14, pady=2)

        # Кнопка обновить
        ctk.CTkButton(
            side, text="↻  Обновить", height=32,
            font=("Roboto", 12), fg_color="#1f2937", hover_color="#374151",
            command=self.refresh
        ).pack(fill="x", padx=10, pady=(20, 4))

    # ── График ────────────────────────────────────────────────────────────

    def _build_chart(self):
        # CTkFrame конфликтует с FigureCanvasTkAgg при resize — используем tk.Frame
        chart_frame = tk.Frame(self, bg="#0d1117", bd=0)
        chart_frame.grid(row=0, column=1, sticky="nsew", padx=(1, 0))

        self._fig = Figure(figsize=(7, 4.5), dpi=96, facecolor="#0d1117")
        self._ax  = self._fig.add_subplot(111)
        self._style_axes()

        self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        # Tooltip при наведении на точки пиков
        self._tooltip_ann = None
        self._scatter_points = []
        self._fig.canvas.mpl_connect("motion_notify_event", self._on_hover)

    def _style_axes(self):
        ax = self._ax
        ax.set_facecolor("#111827")
        ax.tick_params(colors="#555", labelsize=8)
        ax.spines["bottom"].set_color("#222")
        ax.spines["left"].set_color("#222")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.label.set_color("#555")
        ax.xaxis.label.set_color("#555")
        self._fig.tight_layout(pad=1.5)

    # ── Обновление данных ─────────────────────────────────────────────────

    def refresh(self):
        if self.db is None:
            return
        ax = self._ax
        ax.clear()
        self._style_axes()
        self._marker_meta: list[dict] = []  # для tooltip

        hours  = self._period_hours
        series = {}
        for metric in self._active_metrics:
            rows = self.db.get_metric_series(metric, hours=hours)
            if rows:
                times  = [datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S") for r in rows]
                values = [r[1] or 0 for r in rows]
                series[metric] = (times, values)

        if not series:
            ax.text(0.5, 0.5, "Нет данных за выбранный период",
                    transform=ax.transAxes, ha="center", va="center",
                    color="#444", fontsize=12)
            self._canvas.draw()
            return

        # Рисуем линии
        for metric, (times, values) in series.items():
            color = METRIC_COLORS.get(metric, "#ffffff")
            label = METRIC_LABELS.get(metric, metric)
            ax.plot(times, values, color=color, linewidth=1.4,
                    label=label, alpha=0.9)

        # Annotated markers событий
        self._scatter_points = []
        if self._show_markers.get():
            events = self.db.get_events(hours=hours)
            for ev in events:
                try:
                    ts       = datetime.strptime(ev["timestamp"], "%Y-%m-%d %H:%M:%S")
                    severity = ev.get("severity", "warning")
                    metric   = ev.get("metric", "")
                    value    = ev.get("value", 0)
                    color    = SEVERITY_COLORS.get(severity, "#f39c12")

                    # Вертикальная пунктирная линия
                    ax.axvline(x=ts, color=color, linewidth=0.8,
                               linestyle="--", alpha=0.4)

                    # Крупная точка пика прямо на значении метрики
                    sc = ax.scatter(
                        [ts], [value],
                        color=color, s=55, zorder=5,
                        marker="o", edgecolors="white", linewidths=0.8
                    )
                    self._scatter_points.append(sc)

                    meta = {
                        "ts":       ts,
                        "severity": severity,
                        "metric":   metric,
                        "value":    value,
                        "culprit":  ev.get("culprit_process") or "—",
                        "pid":      ev.get("culprit_pid") or "",
                        "delta":    ev.get("delta", 0),
                    }
                    self._marker_meta.append(meta)
                    sc._wp_meta = meta  # привязываем метаданные к scatter
                except Exception:
                    continue

        # Форматирование оси X
        ax.xaxis.set_major_formatter(
            mdates.DateFormatter("%H:%M" if hours <= 24 else "%d.%m %H:%M")
        )
        self._fig.autofmt_xdate(rotation=30, ha="right")

        # Легенда
        if series:
            legend = ax.legend(
                loc="upper left", fontsize=8,
                facecolor="#1f2937", edgecolor="#333",
                labelcolor="#aaa", framealpha=0.8
            )

        ax.set_ylim(bottom=0)
        self._canvas.draw()

    # ── Hover tooltip ─────────────────────────────────────────────────────

    def _on_hover(self, event):
        if event.inaxes != self._ax or not hasattr(self, "_marker_meta"):
            return
        try:
            x_data = event.xdata
            y_data = event.ydata
            if x_data is None or y_data is None:
                return

            hover_dt = mdates.num2date(x_data).replace(tzinfo=None)
            ylim     = self._ax.get_ylim()
            xlim     = self._ax.get_xlim()
            y_range  = max(ylim[1] - ylim[0], 1)
            x_range  = max(xlim[1] - xlim[0], 1)

            closest  = None
            min_dist = float("inf")
            for meta in self._marker_meta:
                dx   = abs((meta["ts"] - hover_dt).total_seconds()) / (x_range * 86400)
                dy   = abs(meta["value"] - y_data) / y_range
                dist = (dx**2 + dy**2) ** 0.5
                if dist < min_dist and dist < 0.05:
                    min_dist = dist
                    closest  = meta

            if self._tooltip_ann:
                try:
                    self._tooltip_ann.remove()
                except Exception:
                    pass
                self._tooltip_ann = None

            if closest:
                pid_str = f" [{closest['pid']}]" if closest.get("pid") else ""
                text = (
                    f"{closest['ts'].strftime('%H:%M:%S')}\n"
                    f"{closest['metric'].replace('_',' ').upper()}\n"
                    f"Значение: {closest['value']:.1f}  Δ{closest.get('delta',0):+.1f}\n"
                    f"→ {closest['culprit']}{pid_str}"
                )
                self._tooltip_ann = self._ax.annotate(
                    text,
                    xy=(mdates.date2num(closest["ts"]), closest["value"]),
                    xytext=(16, 16), textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.5", fc="#1f2937",
                              ec=SEVERITY_COLORS.get(closest["severity"], "#888"),
                              alpha=0.97, linewidth=1.5),
                    color="#eeeeee", fontsize=8.5,
                    arrowprops=dict(arrowstyle="->", color="#555", lw=1),
                    annotation_clip=False,
                )
                self._canvas.draw_idle()
            else:
                self._canvas.draw_idle()
        except Exception:
            pass

    # ── Вспомогательные ──────────────────────────────────────────────────

    def _set_period(self, label: str):
        self._period_hours = self.PERIODS[label]
        for lbl, btn in self._period_btns.items():
            if lbl == label:
                btn.configure(fg_color="#4a9eff", text_color="#fff")
            else:
                btn.configure(fg_color="#1f2937", text_color="#888")
        self.refresh()

    def _toggle_metric(self, key: str, var: tk.BooleanVar):
        if var.get():
            self._active_metrics.add(key)
        else:
            self._active_metrics.discard(key)
        self.refresh()