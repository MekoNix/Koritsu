# Koritsu 2.0 (pre)

Генератор схем из исходного кода для языков Python, C++, C#. Глобальное переписывание с версии 1.0 для лучшей работы.


## Пакеты

- `packages/fragmos` — блок-схемы из кода (Python, C++, C#).
- `packages/uml_generator` — UML: диаграмма классов (`extract_py/cs/cpp` + `build_xml`) и
  диаграмма объектов (`objektis`, статическая трассировка `main()` — код не выполняется).
- `packages/hokoku` — отчёты из DOCX-шаблонов с тегами `{{ключ}}`: типизированные значения
  (текст, markdown, код, картинки, таблицы), подстановка везде (тело, таблицы,
  колонтитулы, текстовые поля), подписи полями SEQ/REF, схемы draw.io, PDF через LibreOffice.

Тесты: `.venv/bin/python -m pytest`. Лаборатории (образцы, галерея PNG, песочница) —
`~/koritsu2-extras/labs/{fragmos,uml,hokoku}`.


## Выкат

Один образ, из него два контейнера — `api` (HTTP) и `worker` (очередь), плюс `caddy`
(TLS и статика сайта) и `anubis` (проверка работой перед сайтом, только в бою).
Состояние — только том `/data`; секреты — `.env` на хосте, вне репозитория.

    cp .env.example .env && $EDITOR .env     # заполнить KORITSU_SECRET
    docker compose up -d --build             # бой
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d   # dev

Домен-заглушка — `koritsu.example` (в `Caddyfile` и `KORITSU_BASE_URL`). Сайт —
React на Vite, живёт в `web/`; в бою его собирает многоступенчатый `web/Dockerfile`, а
отдаёт последняя ступень — образ Caddy; на dev монтируется `web/dist` с диска. Настройки службы перечислены в `.env.example`, все до одной.
