# xfce-zai-limits (рус.)

Виджет для панели **XFCE**, показывающий **лимиты z.ai** — скользящие окна
5 часов / неделя, которые сообщает [Codex CLI][codex], работая через [z.ai][zai].

Работает как нативный `xfce4-genmon-plugin` (как cpugraph/systemload — без
systray, без SNI, без компиляции):

- **графический прогрессбар** на панели (без текста по умолчанию),
- **tooltip при наведении с цифрами** — weekly %, 5ч %, «resets in», баланс
  credits, возраст снимка,
- **клик** → уведомление с деталями,
- цвет зелёный → оранжевый → красный по порогам (опционально через `<css>`).

## Главный инсайт про tooltip

У `xfce4-genmon-plugin` тег tooltip называется **`<tool>`, а не `<tooltip>`** —
частая ошибка в докключиках. Проверено по исходнику 4.3.0
(`panel-plugin/main.c`):

```c
begin = strstr(value, "<tool>");
gtk_widget_set_tooltip_markup(eventbox, g_strndup(begin + 6, ...));
```

Виджет отдаёт `<bar>N</bar>` + `<click>…</click>` + `<tool>…Pango-разметка с
цифрами…</tool>`. Без `<txt>` — на панели только бар.

## Откуда данные (без траты квоты)

Codex и так получает снимок `rate_limits` от z.ai на каждом запросе и пишет его
в rollout-логи `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Виджет находит
самый свежий снимок и рисует. **Без API-запроса, без токенов, без ключа.**

## Требования

- `xfce4-genmon-plugin` (Fedora: `sudo dnf install xfce4-genmon-plugin`)
- Python 3.8+ (только стандартная библиотека)
- Codex CLI, настроенный на z.ai

## Установка

1. Добавь на нужную панель **Generic Monitor** (панель → Add new items… →
   Generic Monitor).
2. В свойствах **Command** — вызывай `python3` **напрямую** (НЕ через
   `bin/zai-limits-genmon.sh` — bash-wrapper с `$(...)` зависает в окружении
   genmon, см. [docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md)):

   ```
   /usr/bin/python3 /home/<вы>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```

3. **Period (s)**: `30`. **Label**: любая (например «LLM»). Готово.

## Цвет бара

По умолчанию `<bar>` использует цвет GTK-темы (синий на Adwaita). Для пороговых
цветов — отдавай тег `<css>` (genmon 4.3.0 поддерживает), см.
[docs/genmon-tags.md](docs/genmon-tags.md). Опционально.

## Настройка порогов

| Переменная | По умолчанию | Что |
| --- | --- | --- |
| `ZAI_LIMITS_WARN` | `70` | %, после которого бар оранжевый |
| `ZAI_LIMITS_CRIT` | `90` | %, после которого бар красный |

## CLI

```bash
python3 zai_limits.py --format text   # человекочитаемо
python3 zai_limits.py --format json   # для waybar/polybar
python3 zai_limits.py --notify        # уведомление
```

## Что покрывается, а что нет

- ✅ **Лимиты Codex / z.ai (rolling 5ч/неделя, gpt-5.x)** — покрыто полностью.
- ⚠️ **GLM через API-ключ z.ai (`pi` на `glm-5.2`)**: `pi` не логирует лимиты.
  Запланирован сборщик `--source zai-api`, см. [docs/zai-api.md](docs/zai-api.md).

## Альтернативы (есть в репо)

- `zai_tray.py` — Gtk.StatusIcon (в legacy systray, не на выбранной панели).
- `zai_indicator.py` — AppIndicator3 (в statusnotifier, но тащит весь SNI-трей
  на эту панель).

На XFCE рекомендуется genmon.

## Лицензия

MIT — см. [LICENSE](LICENSE).

[codex]: https://github.com/openai/codex
[zai]: https://z.ai
