# Koritsu — один образ на два контейнера: `api` и `worker` поднимаются из него
# же, разными командами. Один образ, а не два, потому что код у них общий
# целиком: воркер зовёт те же обработчики, что кладут задание в очередь, и
# второй Dockerfile разошёлся бы с первым на первой же зависимости.
#
# Что здесь есть из системного и почему — по одной причине на строку:
#
#   libreoffice-writer   DOCX → PDF (`hokoku/pdf.py` зовёт `soffice --headless`).
#                        Writer, а не весь LibreOffice: Calc и Impress мы не
#                        зовём никогда, а весят они больше самого Python.
#   fonts-liberation,    кириллица в PDF. Без шрифтов LibreOffice подставит
#   fonts-dejavu-core    что найдёт, и отчёт студента приедет квадратами.
#                        Liberation метрически совпадает с Times New Roman и
#                        Arial — теми, которыми написаны методички.
#   tesseract-ocr +      OCR сканов (`materials/ocr.py`: `tesseract вход stdout
#   -rus, -eng           -l rus+eng`). Языковые данные ставятся отдельными
#                        пакетами; без них tesseract есть, а языка нет, и разбор
#                        молча вернёт пустые страницы.
#   libcairo2            `cairosvg` (PNG из SVG в схемах). Питонья обёртка
#                        грузит системную библиотеку через cffi, колеса с ней
#                        внутри не бывает.
#   xvfb + xauth,        схема draw.io картинкой в собранном DOCX
#   drawio, библиотеки   (`hokoku/images.drawio_to_png`). Подробности — ниже,
#   Electron             отдельным слоем: там же сказано, почему `xauth`
#                        обязателен и почему CLI зовётся `--no-sandbox`.
#
# Чего здесь нет: `git` (код приезжает слоем, а не клоном), компиляторов (все
# зависимости ставятся колёсами) и `/web` (сайт собирает Vite снаружи и отдаёт
# Caddy статикой).
FROM python:3.12-slim

# Питон в контейнере: без буфера (журнал виден сразу, а не после падения), без
# .pyc на томе, без проверки версии pip на каждый запуск.
#
# `PYTHONPATH` — потому что пакеты проекта не устанавливаются (`packages/` —
# каталог модулей, а не дистрибутивы), и импорт идёт путём, ровно как в
# лаборатории: `PYTHONPATH=packages python -m api`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/packages

RUN apt-get update && apt-get install --no-install-recommends -y \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu-core \
        tesseract-ocr \
        tesseract-ocr-rus \
        tesseract-ocr-eng \
        libcairo2 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── draw.io без экрана ────────────────────────────────────────────────────
# Headless-зависимости drawio (Xvfb и прочее) ставятся прямо в образ, чтобы
# схема попадала в собранный Word. До этого слоя `drawio` в образе не было
# вовсе, и `hokoku/images.drawio_to_png` честно отказывался («draw.io CLI не
# найден»), а вне контейнера падал «Trace/breakpoint trap».
#
# draw.io Desktop — это Electron, то есть Chromium. Отсюда три вещи, каждая из
# которых проверена запуском в одноразовом контейнере:
#
#   xvfb        Chromium требует X-сервер даже когда только экспортирует файл;
#               `images.py` сам оборачивает вызов в `xvfb-run`, если тот есть.
#   xauth       **и он тоже**: без него `xvfb-run` не запускается вовсе
#               («xauth command not found»), а ставится он только как
#               Recommends пакета `xvfb`, то есть при `--no-install-recommends`
#               не приезжает. Это ровно та строка, забыв которую, получаешь
#               образ, где всё установлено и ничего не работает.
#   --no-sandbox   песочница Chromium в контейнере не заводится (нет ни
#               setuid-помощника, ни пространств имён у нашего UID) и роняет
#               процесс сигналом; флаг стоит в `images.py`, здесь — только
#               причина, по которой он там.
#
# Версия прибита гвоздём: `latest` у релиза означает, что образ, собранный
# завтра, отличается от собранного сегодня, и разбирательство начинается со
# слова «а какая там была».
#
# Архитектура берётся у dpkg (`amd64`/`arm64`) — под оба имени у релиза есть
# свой `.deb`, и жёстко вписанный `amd64` сломал бы сборку на ARM-машине.
#
# Библиотеки Electron перечислены руками сверх зависимостей самого пакета: его
# `Depends` (libgtk-3-0, libnotify4, libnss3, libxss1, libxtst6, xdg-utils,
# libatspi2.0-0, libuuid1, libsecret-1-0) не называет ни `libgbm1`, ни
# `libasound2` — а без них Chromium не поднимается. Имена с хвостом `t64` —
# это Debian 13 (trixie), база нашего образа; на bookworm они звались бы без
# хвоста, поэтому смена базового образа потребует правки этой строки.
ARG DRAWIO_VERSION=31.4.2
RUN ARCH="$(dpkg --print-architecture)" \
    && curl -fsSL -o /tmp/drawio.deb \
        "https://github.com/jgraph/drawio-desktop/releases/download/v${DRAWIO_VERSION}/drawio-${ARCH}-${DRAWIO_VERSION}.deb" \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        /tmp/drawio.deb \
        xvfb \
        xauth \
        libgbm1 \
        libasound2t64 \
        libnss3 \
        libxss1 \
        libxtst6 \
        libatk-bridge2.0-0t64 \
        libdrm2 \
        libxkbcommon0 \
    && rm -f /tmp/drawio.deb \
    && rm -rf /var/lib/apt/lists/*

# draw.io Desktop при первом запуске лезет проверять обновления — это выключаем.
# А вот каталог настроек ему нужен обязательно: Electron ищет `userData` в
# `$HOME/.config`, и без записываемого HOME падает ещё до экспорта («Failed to
# get 'userData' path», затем «Illegal instruction»). Проверено в собранном
# образе: под UID 10001 без домашнего каталога — падение, с ним — PNG. Поэтому
# пользователь ниже заводится **с** домашним каталогом (`--create-home`), а не
# без него.
ENV DRAWIO_DISABLE_UPDATE=true \
    ELECTRON_DISABLE_SECURITY_WARNINGS=true

# Непривилегированный пользователь с **фиксированным** UID: контейнер работает
# не от root, и файлы на томе тоже не root'овы. Фиксированным — потому что тот
# же UID стоит на файлах тома на хосте, и уехавший номер означает контейнер,
# который не может прочитать свои же данные.
RUN groupadd --gid 10001 koritsu \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin koritsu

WORKDIR /app

# Зависимости — отдельным слоем и до кода: они меняются раз в месяц, код —
# каждый день, и слитые в один слой они означали бы полную переустановку колёс
# на каждую правку.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY packages /app/packages
COPY README.md /app/README.md

# Том. Каталог заводится в образе и отдаётся нашему UID: named volume Docker
# наследует владельца точки монтирования из образа, и без этой строки том
# оказался бы root'овым, а служба — без права записи в него.
RUN mkdir -p /data && chown -R koritsu:koritsu /data
VOLUME ["/data"]

USER koritsu

# Здоровье службы: `/health` для прокси. Проверка стоит в образе, а не только
# в compose, чтобы её унаследовал и тот, кто запустит контейнер руками.
# Воркер её переопределяет своей (см. `docker-compose.yml`): у него порта нет.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('KORITSU_PORT','8000')+'/health', timeout=4).status==200 else 1)"

EXPOSE 8000

# Команда одна на оба контейнера, разница — в аргументе (`serve` или `worker`),
# и это то самое «один образ, два сервиса». `--host 0.0.0.0` умолчанием тут не
# ставится: в `python -m api` он `127.0.0.1` намеренно (открытый порт без
# прокси — забытая настройка, а не удобство), и говорит его compose.
ENTRYPOINT ["python", "-m", "api"]
CMD ["serve", "--host", "0.0.0.0"]
