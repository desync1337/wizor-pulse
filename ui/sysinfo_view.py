"""
sysinfo_view.py — вкладка System Info
Использует tk.Frame вместо CTkScrollableFrame для избежания resize-конфликта.
"""

import platform
import socket
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from datetime import datetime, timedelta

import psutil

try:
    import wmi as _wmi_module
    _WMI = _wmi_module.WMI()
    _WMI_OK = True
except Exception:
    _WMI = None
    _WMI_OK = False

try:
    import win32evtlog
    import win32evtlogutil
    import win32con
    _EVTLOG_OK = True
except Exception:
    _EVTLOG_OK = False


# ─────────────────────────────────────────────────────────────────────────────
# Treeview с тёмной темой
# ─────────────────────────────────────────────────────────────────────────────

def make_dark_treeview(parent, columns: list[tuple[str,str,int]], height=8) -> ttk.Treeview:
    """Создаёт ttk.Treeview со стилем под тёмную тему."""
    style_name = "Dark.Treeview"
    style = ttk.Style()
    style.theme_use("default")
    style.configure(style_name,
        background="#111827", foreground="#cccccc",
        fieldbackground="#111827", rowheight=22,
        font=("Courier", 10), borderwidth=0,
    )
    style.configure(f"{style_name}.Heading",
        background="#1f2937", foreground="#4a9eff",
        font=("Roboto", 10, "bold"), relief="flat",
    )
    style.map(style_name,
        background=[("selected", "#2563eb")],
        foreground=[("selected", "#ffffff")],
    )

    col_ids = [c[0] for c in columns]
    tree = ttk.Treeview(parent, columns=col_ids, show="headings",
                        height=height, style=style_name)
    for col_id, col_label, col_width in columns:
        tree.heading(col_id, text=col_label)
        tree.column(col_id, width=col_width, minwidth=40, stretch=False)

    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)

    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    # Полосатые строки
    tree.tag_configure("odd",      background="#0d1117")
    tree.tag_configure("even",     background="#111827")
    tree.tag_configure("running",  foreground="#2ecc71")
    tree.tag_configure("stopped",  foreground="#e74c3c")
    tree.tag_configure("ok",       foreground="#2ecc71")
    tree.tag_configure("warn",     foreground="#e74c3c")
    tree.tag_configure("critical_evt", foreground="#e74c3c")
    tree.tag_configure("warning_evt",  foreground="#f39c12")

    return tree


# ─────────────────────────────────────────────────────────────────────────────
# SysInfoView
# ─────────────────────────────────────────────────────────────────────────────

class SysInfoView(ctk.CTkFrame):

    AUTO_REFRESH_MS = 60_000

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0d1117", **kwargs)
        self._loading = False
        self._all_services: list[dict] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_content()
        self.after(300, self.refresh)
        self.after(self.AUTO_REFRESH_MS, self._auto_refresh)

    # ── Тулбар ───────────────────────────────────────────────────────────

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color="#111827", corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(bar, text="SYSTEM INFO",
            font=("Roboto", 13, "bold"), text_color="#4a9eff"
        ).pack(side="left", padx=16, pady=8)

        self._status_lbl = ctk.CTkLabel(bar, text="",
            font=("Roboto", 10), text_color="#555")
        self._status_lbl.pack(side="left", padx=8)

        self._refresh_btn = ctk.CTkButton(bar, text="↻  Обновить",
            width=110, height=28, font=("Roboto", 11),
            fg_color="#1f2937", hover_color="#374151",
            command=self.refresh)
        self._refresh_btn.pack(side="right", padx=12, pady=6)

    # ── Контент (нативный tk для избежания resize-конфликта) ─────────────

    def _build_content(self):
        # Главный контейнер — tk.Frame + Canvas для скролла
        container = tk.Frame(self, bg="#0d1117")
        container.grid(row=1, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(container, bg="#0d1117", highlightthickness=0)
        vsb    = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        inner = tk.Frame(canvas, bg="#0d1117")
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_resize(e):
            canvas.itemconfig(inner_id, width=e.width)

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_resize)
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        self._inner = inner
        self._build_sections(inner)

    def _build_sections(self, parent):
        # ── 1. Overview ───────────────────────────────────────────────────
        self._section(parent, "⚙  System Overview")
        ov_frame = tk.Frame(parent, bg="#111827")
        ov_frame.pack(fill="x", padx=8, pady=(0, 10))

        self._kv: dict[str, tk.Label] = {}
        fields = [
            ("os",       "OS"),
            ("hostname", "Hostname"),
            ("uptime",   "Uptime"),
            ("boot",     "Last Boot"),
            ("cpu",      "CPU"),
            ("ram",      "Total RAM"),
            ("python",   "Python"),
        ]
        for key, label in fields:
            row = tk.Frame(ov_frame, bg="#111827")
            row.pack(fill="x", padx=4, pady=1)
            tk.Label(row, text=label, bg="#111827", fg="#555555",
                     font=("Roboto", 10), width=14, anchor="w").pack(side="left", padx=8)
            lbl = tk.Label(row, text="—", bg="#111827", fg="#cccccc",
                           font=("Roboto", 10), anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            self._kv[key] = lbl

        # ── 2. Services ───────────────────────────────────────────────────
        self._section(parent, "🔧  Windows Services")

        svc_ctrl = tk.Frame(parent, bg="#111827")
        svc_ctrl.pack(fill="x", padx=8, pady=(0, 4))

        self._svc_filter = tk.StringVar(value="all")
        for text, val in [("Все", "all"), ("Running", "running"), ("Stopped", "stopped")]:
            tk.Radiobutton(svc_ctrl, text=text, variable=self._svc_filter,
                value=val, bg="#111827", fg="#aaa", selectcolor="#1f2937",
                activebackground="#111827", activeforeground="#4a9eff",
                font=("Roboto", 10), command=self._apply_svc_filter
            ).pack(side="left", padx=8, pady=6)

        self._svc_search = ctk.CTkEntry(svc_ctrl,
            placeholder_text="Поиск...", width=160, height=24, font=("Roboto", 10))
        self._svc_search.pack(side="right", padx=8)
        self._svc_search.bind("<KeyRelease>", lambda e: self._apply_svc_filter())

        svc_tree_frame = tk.Frame(parent, bg="#111827")
        svc_tree_frame.pack(fill="x", padx=8, pady=(0, 10))
        self._svc_tree = make_dark_treeview(svc_tree_frame, [
            ("name",    "Имя службы",   200),
            ("display", "Display Name", 260),
            ("status",  "Статус",        80),
            ("pid",     "PID",           60),
        ], height=8)

        # ── 3. SMART ──────────────────────────────────────────────────────
        self._section(parent, "💾  Disk Health (SMART)")

        smart_note = tk.Label(parent,
            text="  * Требуются права администратора для полного SMART",
            bg="#0d1117", fg="#444", font=("Roboto", 9), anchor="w")
        smart_note.pack(fill="x", padx=12, pady=(0, 2))

        smart_frame = tk.Frame(parent, bg="#111827")
        smart_frame.pack(fill="x", padx=8, pady=(0, 10))
        self._smart_tree = make_dark_treeview(smart_frame, [
            ("drive",  "Диск",   120),
            ("model",  "Модель", 240),
            ("status", "Статус",  80),
            ("serial", "Serial", 160),
        ], height=3)

        # ── 4. Event Log ──────────────────────────────────────────────────
        self._section(parent, "📋  Windows Event Log (ошибки за 24ч)")

        evt_ctrl = tk.Frame(parent, bg="#0d1117")
        evt_ctrl.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkButton(evt_ctrl, text="Открыть Event Viewer",
            width=160, height=26, font=("Roboto", 10),
            fg_color="#1f2937", hover_color="#374151",
            command=lambda: subprocess.Popen("eventvwr.msc", shell=True)
        ).pack(side="left", padx=4, pady=4)

        evt_frame = tk.Frame(parent, bg="#111827")
        evt_frame.pack(fill="x", padx=8, pady=(0, 16))
        self._evt_tree = make_dark_treeview(evt_frame, [
            ("time",     "Время",     130),
            ("source",   "Источник",  130),
            ("event_id", "EventID",    65),
            ("desc",     "Описание",  400),
        ], height=10)

    # ── Данные ────────────────────────────────────────────────────────────

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        self._refresh_btn.configure(state="disabled", text="Загрузка...")
        self._status_lbl.configure(text="Обновление...")
        threading.Thread(target=self._load_all, daemon=True, name="WP-SysInfo").start()

    def _auto_refresh(self):
        self.refresh()
        self.after(self.AUTO_REFRESH_MS, self._auto_refresh)

    def _load_all(self):
        try:
            overview = _get_overview()
            services = _get_services()
            smart    = _get_smart()
            evtlog   = _get_eventlog()
        except Exception as e:
            print(f"[SYSINFO] load error: {e}")
            overview, services, smart, evtlog = {}, [], [], []
        self.after(0, lambda: self._apply(overview, services, smart, evtlog))

    def _apply(self, overview, services, smart, evtlog):
        for key, val in overview.items():
            if key in self._kv:
                self._kv[key].configure(text=val)

        self._all_services = services
        self._apply_svc_filter()
        self._fill_tree(self._smart_tree, smart,
            lambda d: (d["drive"], d["model"], d["status"], d["serial"]),
            lambda d: "warn" if d["status"] not in ("OK", "—") else "ok")
        self._fill_tree(self._evt_tree, evtlog,
            lambda e: (e["time"], e["source"], str(e["event_id"]), e["desc"]),
            lambda e: "critical_evt" if e["level"] == "Critical" else
                      "warning_evt"  if e["level"] in ("Error","Warning") else "")

        ts = datetime.now().strftime("%H:%M:%S")
        self._status_lbl.configure(text=f"Обновлено: {ts}")
        self._refresh_btn.configure(state="normal", text="↻  Обновить")
        self._loading = False

    def _apply_svc_filter(self):
        flt    = self._svc_filter.get()
        search = self._svc_search.get().lower().strip()
        filtered = [s for s in self._all_services
            if (flt == "all" or s["status"] == flt)
            and (not search or search in s["name"].lower()
                 or search in s["display"].lower())]
        self._fill_tree(self._svc_tree, filtered,
            lambda s: (s["name"], s["display"], s["status"], str(s["pid"] or "")),
            lambda s: "running" if s["status"] == "running" else
                      "stopped" if s["status"] == "stopped" else "")

    def _fill_tree(self, tree, items, row_fn, tag_fn):
        tree.delete(*tree.get_children())
        for i, item in enumerate(items):
            values = row_fn(item)
            tags   = (tag_fn(item), "odd" if i % 2 else "even")
            tags   = tuple(t for t in tags if t)
            tree.insert("", "end", values=values, tags=tags)

    def _section(self, parent, title: str):
        tk.Label(parent, text=title, bg="#0d1117", fg="#4a9eff",
                 font=("Roboto", 11, "bold"), anchor="w"
        ).pack(fill="x", padx=12, pady=(12, 2))


# ─────────────────────────────────────────────────────────────────────────────
# Сбор данных
# ─────────────────────────────────────────────────────────────────────────────

def _get_overview() -> dict:
    boot_dt  = datetime.fromtimestamp(psutil.boot_time())
    uptime   = datetime.now() - boot_dt
    d, r     = divmod(int(uptime.total_seconds()), 86400)
    h, m     = divmod(r, 3600)
    uptime_s = f"{d}д {h//60}ч {m//60}мин" if d else f"{h}ч {m//60}мин"
    uptime_s = f"{d}д {h}ч {(r%3600)//60}мин" if d else f"{h}ч {(r%3600)//60}мин"
    return {
        "os":       platform.version()[:64],
        "hostname": socket.gethostname(),
        "uptime":   uptime_s,
        "boot":     boot_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu":      (platform.processor() or "—")[:64],
        "ram":      f"{round(psutil.virtual_memory().total/(1024**3),1)} GB",
        "python":   platform.python_version(),
    }


def _get_services() -> list[dict]:
    result = []
    try:
        for svc in psutil.win_service_iter():
            try:
                info = svc.as_dict()
                result.append({"name": info.get("name",""),
                                "display": info.get("display_name",""),
                                "status": info.get("status",""),
                                "pid": info.get("pid")})
            except Exception:
                continue
    except Exception as e:
        print(f"[SYSINFO] services: {e}")
    return sorted(result, key=lambda s: s["name"].lower())


def _get_smart() -> list[dict]:
    if not _WMI_OK:
        return [{"drive":"—","model":"WMI недоступен","status":"—","serial":"—"}]
    try:
        predict_map = {}
        try:
            for item in _WMI.MSStorageDriver_FailurePredictStatus():
                k = getattr(item, "InstanceName", "")
                predict_map[k] = {
                    "fail":   getattr(item, "PredictFailure", False),
                    "reason": getattr(item, "Reason", 0),
                }
        except Exception:
            pass  # нет прав — просто не будет данных predict

        result = []
        for disk in _WMI.Win32_DiskDrive():
            model  = (getattr(disk,"Model","") or "").strip()[:32]
            serial = (getattr(disk,"SerialNumber","") or "").strip()[:20]
            drive  = (getattr(disk,"DeviceID","") or "").replace("\\\\.\\","")
            index  = str(getattr(disk,"Index",""))
            fail, reason = False, 0
            for k, v in predict_map.items():
                if index in k:
                    fail, reason = v["fail"], v["reason"]
                    break
            status = "WARN" if (fail or reason != 0) else ("OK" if predict_map else "—*")
            result.append({"drive":drive,"model":model,"status":status,"serial":serial})
        return result or [{"drive":"—","model":"Нет дисков","status":"—","serial":"—"}]
    except Exception as e:
        return [{"drive":"—","model":str(e)[:40],"status":"ERR","serial":"—"}]


def _get_eventlog() -> list[dict]:
    if not _EVTLOG_OK:
        return [{"time":"—","source":"pywin32 не установлен",
                 "event_id":0,"desc":"pip install pywin32","level":""}]
    result = []
    cutoff = datetime.now() - timedelta(hours=24)
    for log_name in ("System","Application"):
        try:
            hand  = win32evtlog.OpenEventLog(None, log_name)
            flags = win32evtlog.EVENTLOG_BACKWARDS_READ|win32evtlog.EVENTLOG_SEQUENTIAL_READ
            done  = False
            while not done and len(result) < 50:
                events = win32evtlog.ReadEventLog(hand, flags, 0)
                if not events:
                    break
                for ev in events:
                    if ev.EventType not in (win32con.EVENTLOG_ERROR_TYPE,
                                            win32con.EVENTLOG_WARNING_TYPE):
                        continue
                    try:
                        ts = datetime(*ev.TimeGenerated.timetuple()[:6])
                    except Exception:
                        continue
                    if ts < cutoff:
                        done = True
                        break
                    level = ("Error" if ev.EventType == win32con.EVENTLOG_ERROR_TYPE
                             else "Warning")
                    try:
                        desc = win32evtlogutil.SafeFormatMessage(ev, log_name)
                        desc = " ".join(desc.split())[:200]
                    except Exception:
                        desc = "(описание недоступно)"
                    result.append({"time": ts.strftime("%d.%m %H:%M"),
                                   "source": ev.SourceName[:20],
                                   "event_id": ev.EventID & 0xFFFF,
                                   "desc": desc, "level": level})
            win32evtlog.CloseEventLog(hand)
        except Exception as e:
            print(f"[SYSINFO] evtlog {log_name}: {e}")
    result.sort(key=lambda x: x["time"], reverse=True)
    return result[:50]