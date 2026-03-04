# Wizor Pulse — System Insight Analyzer

Десктопное приложение для мониторинга состояния системы на Windows.  
Живёт в трее, показывает метрики в реальном времени, объясняет причины скачков нагрузки.

## Возможности

- **Realtime Dashboard** — CPU / GPU / RAM / диск / сеть со sparkline-графиками
- **Event Correlation** — при скачке нагрузки автоматически определяет виновный процесс
- **Event Log** — лента событий с временем, дельтой и culprit-процессом
- **History** — интерактивные графики за 1ч / 6ч / 24ч / 7д с annotated markers
- **System Info** — uptime, службы Windows, SMART дисков, Windows Event Log
- **Smart Alerts** — уведомления в трей при превышении порогов
- **Settings** — все параметры настраиваются и сохраняются в JSON

## Структура проекта

```
wizor_pulse/
  main.py
  config.py
  core/
    engine.py        # оркестратор потоков
    hardware.py      # HardwareCollector
    alerts.py        # AlertManager
  database/
    manager.py
  ui/
    dashboard.py
    history_view.py
    sysinfo_view.py
    settings_view.py
  logs/              # создаётся автоматически
```

## Установка

```bash
pip install customtkinter psutil pynvml pystray Pillow matplotlib winotify pywin32
```

> `pynvml` можно заменить на официальный `nvidia-ml-py` (API идентичен):
> ```bash
> pip uninstall pynvml -y && pip install nvidia-ml-py
> ```

## Запуск

```bash
python main.py
```

## Зависимости

| Пакет | Назначение |
|---|---|
| customtkinter | UI фреймворк |
| psutil | метрики CPU / RAM / диск / сеть / службы |
| pynvml / nvidia-ml-py | метрики NVIDIA GPU |
| pystray | иконка в системном трее |
| Pillow | генерация иконки |
| matplotlib | графики в History |
| winotify | Windows toast-уведомления |
| pywin32 | Windows Event Log (опционально) |
| wmi | SMART дисков, WMI-метрики (опционально) |
