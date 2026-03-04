"""
settings_view.py — вкладка Settings
Настройка порогов алёртов, интервалов, темы и поведения при запуске.
Изменения сохраняются в wizor_config.json через cfg.save().
"""

import customtkinter as ctk
from config import cfg


class SettingsView(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0d1117", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()

        scroll = ctk.CTkScrollableFrame(self, fg_color="#0d1117")
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        self._widgets: dict = {}
        self._build_general(scroll)
        self._build_thresholds(scroll)
        self._build_data(scroll)

    # ── Тулбар ───────────────────────────────────────────────────────────

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color="#111827", corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            bar, text="SETTINGS",
            font=("Roboto", 13, "bold"), text_color="#4a9eff"
        ).pack(side="left", padx=16, pady=8)

        ctk.CTkButton(
            bar, text="✓  Сохранить", width=120, height=28,
            font=("Roboto", 11), fg_color="#2563eb", hover_color="#1d4ed8",
            command=self._save
        ).pack(side="right", padx=6, pady=6)

        ctk.CTkButton(
            bar, text="↺  Сбросить", width=110, height=28,
            font=("Roboto", 11), fg_color="#1f2937", hover_color="#374151",
            command=self._reset
        ).pack(side="right", padx=6, pady=6)

        self._status = ctk.CTkLabel(bar, text="", font=("Roboto", 10), text_color="#2ecc71")
        self._status.pack(side="right", padx=10)

    # ── Секция: Основные ─────────────────────────────────────────────────

    def _build_general(self, parent):
        self._section(parent, "⚙  Основные настройки")
        frame = self._card(parent)

        self._widgets["collect_interval"] = self._slider_row(
            frame, "Интервал сбора метрик (сек)",
            cfg.collect_interval, 1, 10, 9
        )
        self._widgets["db_write_interval"] = self._slider_row(
            frame, "Интервал записи в БД (сек)",
            cfg.db_write_interval, 2, 30, 28
        )
        self._widgets["procs_interval"] = self._slider_row(
            frame, "Обновление процессов (сек)",
            cfg.procs_interval, 5, 60, 11
        )
        self._widgets["start_hidden"] = self._toggle_row(
            frame, "Запускать свёрнутым в трей",
            cfg.start_hidden
        )
        self._widgets["theme"] = self._dropdown_row(
            frame, "Тема оформления",
            cfg.theme, ["dark", "light", "system"]
        )

    # ── Секция: Пороги алёртов ───────────────────────────────────────────

    def _build_thresholds(self, parent):
        self._section(parent, "🔔  Пороги алёртов")
        frame = self._card(parent)

        thresholds = cfg.alert_thresholds
        specs = [
            ("cpu_load",     "CPU нагрузка",       "%",    95),
            ("ram_load",     "RAM нагрузка",        "%",    90),
            ("gpu_temp",     "GPU температура",     "°C",   85),
            ("disk_usage",   "Диск заполнен",       "%",    95),
            ("net_download", "Сеть (входящая)",     "MB/s", 50),
        ]

        self._widgets["thresholds"] = {}
        for key, label, unit, default in specs:
            current = thresholds.get(key, {}).get("critical", default)
            self._widgets["thresholds"][key] = self._slider_row(
                frame, f"{label}  ({unit})",
                current, 1, 100 if unit in ("%",) else 120, None,
                val_suffix=unit
            )

        self._widgets["alert_cooldown_sec"] = self._slider_row(
            frame, "Антиспам (мин между повторами)",
            cfg.alert_cooldown_sec // 60, 1, 30, 29,
            val_suffix="мин"
        )

    # ── Секция: Хранение данных ──────────────────────────────────────────

    def _build_data(self, parent):
        self._section(parent, "🗄  Хранение данных")
        frame = self._card(parent)

        self._widgets["data_retention_days"] = self._slider_row(
            frame, "Хранить данные (дней)",
            cfg.data_retention_days, 1, 90, 89
        )
        self._widgets["event_log_max_memory"] = self._slider_row(
            frame, "Event Log в памяти (событий)",
            cfg.event_log_max_memory, 50, 500, 450
        )
        self._widgets["spike_delta_threshold"] = self._slider_row(
            frame, "Порог spike (дельта, pp)",
            cfg.spike_delta_threshold, 5, 50, 45
        )

    # ── Сохранение / сброс ────────────────────────────────────────────────

    def _save(self):
        try:
            cfg.collect_interval     = int(self._widgets["collect_interval"].get())
            cfg.db_write_interval    = int(self._widgets["db_write_interval"].get())
            cfg.procs_interval       = int(self._widgets["procs_interval"].get())
            cfg.start_hidden         = bool(self._widgets["start_hidden"].get())
            cfg.data_retention_days  = int(self._widgets["data_retention_days"].get())
            cfg.event_log_max_memory = int(self._widgets["event_log_max_memory"].get())
            cfg.spike_delta_threshold= int(self._widgets["spike_delta_threshold"].get())
            cfg.alert_cooldown_sec   = int(self._widgets["alert_cooldown_sec"].get()) * 60
            cfg.theme                = self._widgets["theme"].get()

            # Пороги
            for key, slider in self._widgets["thresholds"].items():
                val = int(slider.get())
                if key not in cfg.alert_thresholds:
                    cfg.alert_thresholds[key] = {}
                cfg.alert_thresholds[key]["critical"] = val

            cfg.save()
            self._status.configure(text="✓ Сохранено", text_color="#2ecc71")
            self.after(3000, lambda: self._status.configure(text=""))
        except Exception as e:
            self._status.configure(text=f"Ошибка: {e}", text_color="#e74c3c")

    def _reset(self):
        cfg.reset()
        self._status.configure(text="↺ Сброшено к дефолтам", text_color="#f39c12")
        self.after(3000, lambda: self._status.configure(text=""))

    # ── Строительные хелперы ─────────────────────────────────────────────

    def _section(self, parent, title: str):
        ctk.CTkLabel(
            parent, text=title,
            font=("Roboto", 12, "bold"), text_color="#4a9eff"
        ).pack(anchor="w", padx=12, pady=(14, 2))

    def _card(self, parent) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="#111827", corner_radius=8)
        frame.pack(fill="x", padx=8, pady=(0, 6))
        return frame

    def _slider_row(self, parent, label: str, value, min_v, max_v, steps,
                    val_suffix: str = "") -> ctk.CTkSlider:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=5)

        ctk.CTkLabel(
            row, text=label, font=("Roboto", 11),
            text_color="#aaa", width=240, anchor="w"
        ).pack(side="left")

        val_label = ctk.CTkLabel(
            row, text=f"{int(value)}{val_suffix}",
            font=("Roboto", 11, "bold"), text_color="#4a9eff", width=60
        )
        val_label.pack(side="right")

        slider = ctk.CTkSlider(
            row, from_=min_v, to=max_v,
            number_of_steps=steps or int(max_v - min_v),
            fg_color="#1f2937", progress_color="#2563eb",
            button_color="#4a9eff", button_hover_color="#60a5fa",
            width=200
        )
        slider.set(value)
        slider.pack(side="right", padx=10)
        slider.configure(command=lambda v, l=val_label, s=val_suffix:
                         l.configure(text=f"{int(v)}{s}"))
        return slider

    def _toggle_row(self, parent, label: str, value: bool) -> ctk.CTkSwitch:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(
            row, text=label, font=("Roboto", 11), text_color="#aaa", anchor="w"
        ).pack(side="left")
        switch = ctk.CTkSwitch(
            row, text="", fg_color="#1f2937", progress_color="#2563eb",
            button_color="#4a9eff"
        )
        if value:
            switch.select()
        else:
            switch.deselect()
        switch.pack(side="right")
        return switch

    def _dropdown_row(self, parent, label: str, value: str,
                      options: list) -> ctk.CTkOptionMenu:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(
            row, text=label, font=("Roboto", 11), text_color="#aaa", anchor="w"
        ).pack(side="left")
        menu = ctk.CTkOptionMenu(
            row, values=options,
            font=("Roboto", 11), fg_color="#1f2937",
            button_color="#2563eb", button_hover_color="#1d4ed8",
            dropdown_fg_color="#1f2937", width=120
        )
        menu.set(value)
        menu.pack(side="right")
        return menu