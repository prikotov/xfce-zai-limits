# xfce-zai-limits (рус.)

Виджет для панели **XFCE**, показывающий **лимиты z.ai** — скользящие окна
5 часов / неделя, которые сообщает [Codex CLI][codex], работая через [z.ai][zai].

Работает как нативный `xfce4-genmon-plugin` (как cpugraph/systemload — без
systray, без SNI, без компиляции):

- **графический прогрессбар** на панели (без текста по умолчанию),
- **tooltip при наведении с цифрами** — weekly %, 5ч %, MCP %, «resets in»,
  баланс credits, возраст снимка,
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
- Python 3.8+ (только стандартная библиотека; `pygobject`/`cairo` для genmon не нужны)
- OpenAI Codex CLI — для метрики **codex** (читает rollout-логи)
- z.ai API-ключ — для метрики **z.ai / GLM**: pi `~/.pi/agent/auth.json`
  (`zai.key`) или `$ZAI_API_KEY`. Без него работает только bar codex.

## Установка — два бара (codex + z.ai)

У genmon `<bar>` только один бар, поэтому добавь **два Generic Monitor** на
панель — по одному на метрику:

1. **codex** — Command:
   ```
   /usr/bin/python3 /home/<вы>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```
2. **z.ai** — Command (обрати внимание на `ZAI_BAR_METRIC=zai`):
   ```
   env ZAI_BAR_METRIC=zai /usr/bin/python3 /home/<вы>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```

   Хочешь, чтобы z.ai-бар показывал **недельное** окно, а не 5-часовое?
   Поставь `ZAI_BAR_METRIC=zai-weekly`. В любом случае в tooltip будут все
   три окна (weekly / 5h / MCP).

Period `30` для обоих. Tooltip у каждого — только свой провайдер; `<bar>`
окрашивается зелёный/оранжевый/красный по порогам автоматически (через тег
`<css>`).

> **Вызывай `python3` напрямую** — не указывай genmon на `bin/*.sh`;
> bash-обёртка с `$(...)` зависает в spawn-окружении genmon
> ([docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md)).

### Подписи (gotcha genmon)

Подпись на панели — это xfconf-свойство **`/text`** (НЕ `/label` и НЕ `/title`),
и genmon перезаписывает его из памяти при сохранении панели. Ставь при
выключенной панели, иначе собьётся:

```bash
xfce4-panel -q
xfconf-query -c xfce4-panel -p /plugins/plugin-<N>/text -s "codex"
xfconf-query -c xfce4-panel -p /plugins/plugin-<M>/text -s "z.ai"
# потом снова запусти xfce4-panel
```

Полная таблица тегов/свойств: [docs/genmon-tags.md](docs/genmon-tags.md).

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
