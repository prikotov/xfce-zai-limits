# xfce-zai-limits (рус.)

Виджет для панели **XFCE**, показывающий **лимиты z.ai** — скользящие окна
5 часов / неделя, которые сообщает [Codex CLI][codex], когда работает через
[z.ai][zai]. Прогресс-бар на панели + подробная всплывашка при наведении.

```
z.ai  75%  ▮▮▮▮▯     ← на панели
```

При наведении:

```
z.ai limits

weekly:  75%   resets in 5d 22h  (25 июл)
5h:      42%   resets in 3h 9m   (19 июл)

credits: balance 12.50

updated 3m ago
read from Codex logs — refreshes as you use
```

## Почему так

Codex и так получает снимок `rate_limits` от z.ai на каждом запросе и
**записывает его в свои rollout-логи**
(`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`). Виджет просто находит самый
свежий снимок и рисует его. **Без API-запроса, без траты квоты, без ключа.**

Цена: число обновляется только когда Codex реально делает запрос — но именно
тогда лимит и меняется. Всплывашка всегда показывает возраст снимка.

## Установка и настройка

Нужен `xfce4-genmon-plugin` ≥ 4.18 и Python 3.8+ (только стандартная
библиотека).

```bash
# Fedora
sudo dnf install xfce4-genmon-plugin
# Debian/Ubuntu
sudo apt install xfce4-genmon-plugin
```

```bash
git clone https://github.com/<you>/xfce-zai-limits.git ~/src/xfce-zai-limits
~/src/xfce-zai-limits/bin/zai-limits-genmon.sh   # проверка: печатает XML genmon
```

На панель: правый клик по панели → **Add new items…** → **Generic Monitor** →
**Add**. В свойствах:

- **Command**: `/home/<вы>/src/xfce-zai-limits/bin/zai-limits-genmon.sh`
- **Period (s)**: `30`
- **Label**: пусто
- галка **Use a progress bar** — по желанию

## Настройка порогов и цветов

Через переменные окружения (см. [README.md](README.md#customize) — полная
таблица). Основные:

| Переменная | По умолчанию | Что |
| --- | --- | --- |
| `ZAI_LIMITS_WARN` | `70` | %, после которого бар оранжевый |
| `ZAI_LIMITS_CRIT` | `90` | %, после которого бар красный |

## Что покрывается, а что нет

- ✅ **Лимиты Codex / z.ai (rolling 5ч/неделя, модели gpt-5.x через ChatGPT-логин)**
  — это то, чего чаще всего не хватает. Покрыто полностью.
- ⚠️ **GLM-модели через API-ключ z.ai (например `pi` на `glm-5.2`)**: `pi` сейчас
  не логирует лимиты, а у z.ai для GLM другая модель квот (API-кредиты).
  Запланирован сборщик `--source zai-api`, см. [docs/zai-api.md](docs/zai-api.md).

## Лицензия

MIT — см. [LICENSE](LICENSE).

[codex]: https://github.com/openai/codex
[zai]: https://z.ai
