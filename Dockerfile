# Koritsu — один образ на два контейнера (решение владельца §1: `api` и `worker`
# поднимаются из него же, разными командами). Один образ, а не два, потому что
# код у них общий целиком: воркер зовёт те же обработчики, что кладут задание в
# очередь, и второй Dockerfile разошёлся бы с первым на первой же зависимости.
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
#
# Чего здесь нет: `git` (код приезжает слоем, а не клоном), компиляторов (все
# зависимости ставятся колёсами) и `/web` (сайт собирает Vite снаружи и отдаёт
# Caddy статикой, §11).
FROM python:3.12-slim

# Питон в контейнере: без буфера (журнал виден сразу, а не после падения), без
# .pyc на томе, без проверки версии pip на каждый запуск.
#
# `PYTHONPATH` — потому что пакеты проекта не устанавливаются (решение
# владельца: `packages/` — каталог модулей, а не дистрибутивы), и импорт идёт
# путём, ровно как в лаборатории: `PYTHONPATH=packages python -m api`.
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
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь с **фиксированным** UID (решение владельца
# §2: «контейнер работает от фиксированного UID, файлы на томе не root»).
# Фиксированным — потому что тот же UID стоит на файлах тома на хосте, и
# уехавший номер означает контейнер, который не может прочитать свои же данные.
RUN groupadd --gid 10001 koritsu \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin koritsu

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

# Здоровье службы (§7: «/health для прокси»). Проверка стоит в образе, а не
# только в compose, чтобы её унаследовал и тот, кто запустит контейнер руками.
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
