AI-помощник для подготовки товарных описаний (КИП)

Прототип: по JSON с данными о приборе (название, производитель, характеристики, описание) генерирует
черновик карточки товара для B2B-магазина: SEO-заголовок (≤ 70 симв.), SEO-описание (800-1200 симв.),
список характеристик, 3-5 поисковых запросов, commercial-блок для менеджера и список того, что нужно уточнить.

Главный принцип - модель не выдумывает характеристики (см. [DECISIONS.md](DECISIONS.md)).

Установка

Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # впишите ANTHROPIC_API_KEY (файл .env в .gitignore)
```

Запуск

```bash
export PYTHONPATH=src              # Windows PowerShell: $env:PYTHONPATH="src"

# оба примера из каталога → out/*.json и out/*.md
python -m cardgen examples/input

# один файл, только Markdown
python -m cardgen examples/input/manometer_dm02.json -f md -o out

# из stdin
cat examples/input/thermometer_tc20.json | python -m cardgen -

# только проверить входные данные, без обращения к API
python -m cardgen examples/input --dry-run
```

 Товары из фида (YML или текстовая выгрузка СОЮЗ-ПРИБОР)
Формат фида определяется автоматически: XML (YML) или текстовая построчная выгрузка
(`name URL category_id brand article [image] price RUR ...`). Разбор текстового формата - `src/cardgen/catalog_parser.py`;
он же работает отдельно и сохраняет весь каталог в JSON/CSV:

```bash
python -m cardgen.catalog_parser examples/catalog_sample.txt -o catalog_out   # products.json, products.csv, invalid_lines.txt
```
В текстовой выгрузке нет характеристик и описаний, только название, бренд, артикул, фото и ссылка. Поэтому в
карточке большинство характеристик будет «данных нет», а описание - короче 800 символов с пояснением причины.
Параметр `--min-specs` для такого формата не используйте.

 Товары из YML-фида
```bash
# самое простое: взять первые 2 товара из фида souz-pribor.ru (с 3+ заполненными параметрами)
python -m cardgen --feed --limit 2 --min-specs 3
```
Другой адрес можно задать значением `--feed <URL или файл>` либо `FEED_URL` в `.env`.

Больше возможностей:

```bash
# первые 2 товара, в названии которых есть «манометр»
python -m cardgen --feed https://www.souz-pribor.ru/yml/any/feed.xml --search манометр --limit 2

# конкретные товары по id из фида
python -m cardgen --feed https://www.souz-pribor.ru/yml/any/feed.xml --offer-id 123 --offer-id 456
```

Фид читается потоково, `<offer>` преобразуется в `name / manufacturer / specs (из <param>) / description`
(HTML из описания вычищается, цена и наличие не берутся). `--feed` принимает и локальный файл.

Вход - один JSON-объект или массив объектов:

```json
{
  "name": "Манометр показывающий DM 02",
  "manufacturer": "Манотомь",
  "specs": {"диапазон измерений": "0-1,6 МПа", "класс точности": "1,5"},
  "description": "Прибор предназначен для ..."
}
```

 Другой провайдер (OpenAI и совместимые)
В `.env` вместо `ANTHROPIC_API_KEY` задайте `OPENAI_API_KEY` (и при желании `OPENAI_MODEL`, `OPENAI_BASE_URL`
для OpenAI-совместимых сервисов). Провайдер выбирается автоматически по найденному ключу, либо явно:
`--provider openai` или `LLM_PROVIDER=openai`.

Модель можно сменить: `--model <id>` или `ANTHROPIC_MODEL` в `.env` (по умолчанию `claude-sonnet-5-5`).

Результат

Для каждого товара создаются `<имя>.json` (структурированный), `<имя>.md` (удобен для копирования) и `<имя>.html` (готовая карточка с фото: откройте в браузере). Если у товара есть фото (`<picture>` в фиде или поле `images` во входном JSON), главное фото стоит сразу под заголовком, остальные идут галереей.
Готовые примеры: [`examples/output/`](examples/output/).
В JSON есть `status` (`ok` / `needs_review`), `warnings`, `missing_input_fields`, `attempts`.

Тесты

```bash
pytest
```

Тесты не обращаются к API (используется поддельный клиент).

Структура

```
src/cardgen/
  schema.py    разбор и нормализация входа, сбор списка характеристик, «данных нет»
  prompts.py   системный промпт, JSON-схема ответа (tool use), сборка запроса
  llm.py       клиент Anthropic API, обработка ошибок
  validate.py  проверка ответа: длины, числа и «рискованные» факты, которых нет во входе
  pipeline.py  генерация → проверка → перегенерация с замечаниями
  render.py    Markdown-карточка
  cli.py       командная строка
tests/         pytest
examples/      входные данные и результаты
```
