# Koritsu 2.0 (beta)

Набор инструментов для учебных работ: отчёты из DOCX-шаблонов, блок-схемы и UML из
исходного кода (Python, C++, C#), решения задач с проверкой, всё через веб-сайт с
аккаунтами, пространствами и очередью заданий. Переписан с нуля относительно версии 1.0.


## Быстрый старт

Нужны Docker и Docker Compose. Всё состояние службы живёт в томе `/data`, секреты — в `.env`
рядом с `docker-compose.yml`, вне репозитория.

    git clone https://github.com/MekoNix/Koritsu.git && cd Koritsu
    cp .env.example .env && $EDITOR .env     # KORITSU_SECRET и KORITSU_DOMAIN
    docker compose up -d --build

`KORITSU_DOMAIN=http://<адрес сервера>` (или `http://localhost`) поднимает сайт на порту 80
без TLS; с настоящим доменом Caddy выпустит сертификат сам. Сайт собирается внутри образа,
Node на хосте не нужен. Ключ модели задаётся в настройках аккаунта или общим ключом службы в
`.env`; без ключа работают схемы, шаблоны и проверки, а прогоны модели отказывают понятной
ошибкой. Для разработки есть dev-состав (`docker-compose.dev.yml`): порт службы наружу,
сайт — из `web/dist` с диска после `pnpm build`, Caddy на `127.0.0.1:8080`.


## Пакеты

- `packages/fragmos` — блок-схемы из кода (Python, C++, C#).
- `packages/uml_generator` — UML: диаграмма классов (`extract_py/cs/cpp` + `build_xml`) и
  диаграмма объектов (`objektis`, статическая трассировка `main()` — код не выполняется).
- `packages/hokoku` — отчёты из DOCX-шаблонов с тегами `{{ключ}}`: типизированные значения
  (текст, markdown, код, картинки, таблицы), подстановка везде (тело, таблицы,
  колонтитулы, текстовые поля), подписи полями SEQ/REF, схемы draw.io, PDF через LibreOffice.

Тесты: `.venv/bin/python -m pytest`. Лаборатории (образцы, галерея PNG, песочница)
живут вне репозитория.


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
