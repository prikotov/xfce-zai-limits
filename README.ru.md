# xfce-zai-limits (рус.)

Индикатор для панели **XFCE**, показывающий **лимиты z.ai** — скользящие окна
5 часов / неделя, которые сообщает [Codex CLI][codex], работая через [z.ai][zai].

**Рекомендуемый способ — индикатор `zai_indicator.py`** (AppIndicator3).
Поставь `xfce4-statusnotifier-plugin` на нужную панель (например, в левый
док мониторинга, рядом с cpugraph/systemload), и индикатор окажется там:
- компактная **иконка-прогрессбар** (без текста на панели),
- **tooltip при наведении с полными цифрами** — weekly %, 5ч %, «resets in»,
  баланс credits, возраст снимка,
- **меню по клику** (Обновить / Уведомление / Выйти),
- цвет зелёный → оранжевый → красный по мере приближения к лимиту.

Также есть режимы `zai_tray.py` (Gtk.StatusIcon → в старый systray, обычно
нижняя панель) и `zai_limits.py --format genmon` (для xfce4-genmon-plugin,
**но без цифр в tooltip** — у genmon нет тега `<tooltip>`).

## Почему так

Codex и так получает снимок `rate_limits` от z.ai на каждом запросе и
**записывает его в свои rollout-логи**
(`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`). Инструмент находит самый
свежий снимок и рисует его. **Без API-запроса, без траты квоты, без ключа.**

Цена: число обновляется только когда Codex реально делает запрос — но именно
тогда лимит и меняется. Tooltip всегда показывает возраст снимка.

## Требования

- Python 3.8+ с `pygobject` + `cairo` (уже стоят на любом XFCE).
- **`xfce4-statusnotifier-plugin`** на панели, где нужен индикатор.
  Fedora: `sudo dnf install xfce4-statusnotifier-plugin`.
- Codex CLI, настроенный на z.ai.

## Быстрый старт

```bash
git clone https://github.com/<you>/xfce-zai-limits.git ~/src/xfce-zai-limits
python3 ~/src/xfce-zai-limits/zai_indicator.py &
```

Если на панели ещё нет элемента «StatusNotifier» — добавь: панель →
**Add new items…** → **StatusNotifier**. Иконка появится там. Наведи → лимиты.

### Автозапуск при входе (systemd user-unit)

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/zai-indicator.service <<'EOF'
[Unit]
Description=z.ai limits panel indicator
After=graphical-session.target
[Service]
ExecStart=/usr/bin/python3 /home/<вы>/src/xfce-zai-limits/zai_indicator.py
Restart=on-failure
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now zai-indicator.service
```

(Либо классический XDG-autostart: `examples/zai-tray.autostart.desktop` с
`Exec=` → `zai_indicator.py`, в `~/.config/autostart/`.)```

### Настройка

Переменные окружения:

| Переменная | По умолчанию | Что |
| --- | --- | --- |
| `ZAI_TRAY_REFRESH` | `30` | интервал обновления, секунды |
| `ZAI_TRAY_ICON_SIZE` | `24` | базовый размер иконки (подстраивается под трей) |
| `ZAI_LIMITS_WARN` | `70` | %, после которого бар оранжевый |
| `ZAI_LIMITS_CRIT` | `90` | %, после которого бар красный |

## CLI

```bash
python3 zai_limits.py --format text   # человекочитаемо, разово
python3 zai_limits.py --format json   # для waybar/polybar/i3blocks
python3 zai_limits.py --format genmon # для xfce4-genmon-plugin (без цифр в tooltip)
python3 zai_limits.py --notify        # выкинуть уведомление
```

## Что покрывается, а что нет

- ✅ **Лимиты Codex / z.ai (rolling 5ч/неделя, модели gpt-5.x)** — покрыто
  полностью. Это то, чего чаще всего не хватает.
- ⚠️ **GLM-модели через API-ключ z.ai (`pi` на `glm-5.2`)**: `pi` не логирует
  лимиты, у z.ai для GLM другая модель квот (API-кредиты). Запланирован сборщик
  `--source zai-api`, см. [docs/zai-api.md](docs/zai-api.md).

## Файлы

```
zai_tray.py                # трей-индикатор (рекомендуется) — StatusIcon + cairo
zai_limits.py              # сбор данных + форматтеры genmon/text/json/notify
bin/zai-limits-genmon.sh   # опциональная обёртка для genmon (с оговорками)
examples/zai-tray.autostart.desktop   # скопировать в ~/.config/autostart/
docs/                      # заметки исследования
```

## Лицензия

MIT — см. [LICENSE](LICENSE).

[codex]: https://github.com/openai/codex
[zai]: https://z.ai
