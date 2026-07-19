# xfce-zai-limits (рус.)

Индикатор для панели **XFCE**, показывающий **лимиты z.ai** — скользящие окна
5 часов / неделя, которые сообщает [Codex CLI][codex], работая через [z.ai][zai].

**Рекомендуемый способ — индикатор в системном трее** (`zai_tray.py`):
- компактная **иконка-прогрессбар** в трее панели (без текста на панели),
- **tooltip при наведении с полными цифрами** — weekly %, 5ч %, «resets in»,
  баланс credits, возраст снимка,
- **клик** → уведомление с теми же деталями,
- **правый клик** → меню (Обновить / Выйти),
- цвет зелёный → оранжевый → красный по мере приближения к лимиту.

Также есть режим для `xfce4-genmon-plugin` (`zai_limits.py --format genmon`),
но **genmon не умеет показывать цифры в tooltip** (его tooltip всегда = строка
command, см. [docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md)). Если
нужны цифры при наведении — используй трей-индикатор.

## Почему так

Codex и так получает снимок `rate_limits` от z.ai на каждом запросе и
**записывает его в свои rollout-логи**
(`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`). Инструмент находит самый
свежий снимок и рисует его. **Без API-запроса, без траты квоты, без ключа.**

Цена: число обновляется только когда Codex реально делает запрос — но именно
тогда лимит и меняется. Tooltip всегда показывает возраст снимка.

## Требования

- Python 3.8+ (для трей-иконки ещё `pygobject` + `cairo` — уже стоят на любом
  XFCE).
- Панель XFCE с плагином **Status Tray** (в `xfce4-panel` по умолчанию).
- Codex CLI, настроенный на z.ai.

Fedora: `sudo dnf install python3-gobject python3-cairo`.

## Быстрый старт — трей-индикатор

```bash
git clone https://github.com/<you>/xfce-zai-limits.git ~/src/xfce-zai-limits
python3 ~/src/xfce-zai-limits/zai_tray.py &
```

В трее появится иконка. Наведи → увидишь лимиты.

### Автозапуск при входе

```bash
cp ~/src/xfce-zai-limits/examples/zai-tray.autostart.desktop \
   ~/.config/autostart/zai-tray.desktop
# если клонировал в другое место — поправь путь в Exec=
```

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
