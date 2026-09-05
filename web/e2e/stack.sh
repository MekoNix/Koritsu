#!/usr/bin/env bash
# stack.sh — стенд сайта: настоящая служба, настоящий воркер, поддельная модель.
#
#     web/e2e/stack.sh start [каталог]    поднять всё и дождаться /health
#     web/e2e/stack.sh wait  [каталог]    дождаться /health уже поднятого
#     web/e2e/stack.sh stop  [каталог]    остановить всё
#     web/e2e/stack.sh status [каталог]   кто жив и где логи
#     web/e2e/stack.sh env   [каталог]    переменные стенда для `eval`
#
# Имена переменных и функций здесь латиницей — не по вкусу: bash не признаёт
# кириллицу в именах вовсе (`КОРЕНЬ=…` он читает как команду). Комментарии и
# сообщения — по-русски, как во всём репозитории.
#
# Три процесса: `fake-llm` (модель), `api serve` (служба), `api worker`
# (очередь). База доводится `api migrate` до подъёма — тем же порядком, что и на
# выкате, иначе служба и воркер мигрировали бы одну SQLite вдвоём.
#
# Каталог тома — временный и НЕ `/data`: стенд поднимается и сносится по многу
# раз подряд, и делать это на боевом томе нельзя. Не назвали каталог — берётся
# `mktemp -d`, и путь запоминается в `/tmp/koritsu-e2e-last`, чтобы `stop` и
# `wait` не требовали его повторять.
#
# Ключа поставщика у стенда нет и не должно быть: общий ключ — слово `fake-key`,
# его принимает поддельный сервер и не принял бы настоящий. Прогоны при этом
# идут настоящие — через очередь, подпроцесс задания и слой `llm`.
#
# Переменные (все с умолчаниями):
#   API_PORT   8006   порт службы
#   FAKE_PORT  8016   порт поддельной модели
#   PYTHON            интерпретатор (умолч. общий venv репозитория)
#   FAKE_DELAY_MS     задержка между кусками потока у подделки (умолч. 30)
#   FAKE_CHUNK        знаков в куске потока (умолч. 48)
#   KORITSU_REGISTRATIONS_PER_IP_PER_DAY  на стенде 1000, боевое — 5
#   KORITSU_ADMIN_DOMAIN  имя, на котором живёт админка (умолч. 127.0.0.1)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
marker="/tmp/koritsu-e2e-last"

PYTHON="${PYTHON:-$root/.venv/bin/python}"
API_PORT="${API_PORT:-8006}"
FAKE_PORT="${FAKE_PORT:-8016}"
host="127.0.0.1"

cmd="${1:-start}"
dir="${2:-${KORITSU_E2E_DIR:-}}"

# ── каталог тома ─────────────────────────────────────────────────────────────
if [ -z "$dir" ]; then
  if [ "$cmd" = "start" ]; then
    dir="$(mktemp -d /tmp/koritsu-e2e-XXXXXX)"
  elif [ -f "$marker" ]; then
    dir="$(cat "$marker")"
  else
    echo "стенд: не назван каталог тома и нет $marker" >&2
    exit 2
  fi
fi
mkdir -p "$dir"
dir="$(cd "$dir" && pwd)"

# Секрет живёт в каталоге тома, а не в скрипте: перезапуск стенда не должен
# обнулять сессии и ключи, зашифрованные прежним секретом.
secret_file="$dir/secret"
[ -s "$secret_file" ] || head -c 48 /dev/urandom | base64 | tr -d '\n' > "$secret_file"

export PYTHONPATH="$root/packages"
export KORITSU_DATA_DIR="$dir"
export KORITSU_SECRET="$(cat "$secret_file")"
export KORITSU_ENV=dev
# Порт открыт напрямую, без Caddy: верить `X-Forwarded-For` здесь означало бы,
# что лимит регистраций по IP обходится одной строкой заголовка.
export KORITSU_TRUST_PROXY=no
# Ссылка в письме (её вылавливает `smoke.sh` из журнала службы) обязана вести на
# тот же порт, иначе токен подтверждения некуда нести.
export KORITSU_BASE_URL="http://$host:$API_PORT"
# Общий ключ поставщика: с ним прогон идёт и у человека без своего ключа.
export KORITSU_PROVIDER_KEY_DEEPSEEK=fake-key
# То самое, ради чего заведена dev-настройка: пресет `deepseek` ходит на стенд.
export KORITSU_LLM_BASE_URL_DEEPSEEK="http://$host:$FAKE_PORT"
# Очередь опрашивается чаще боевого: на стенде важна не экономия запросов к
# базе, а то, что задание начинается сразу и проверка не ждёт секунду впустую.
export KORITSU_WORKER_POLL_S="${KORITSU_WORKER_POLL_S:-0.2}"
# Регистраций с одного адреса. Боевые пять в сутки кончаются на шестом прогоне
# проверки — а их бывают десятки подряд, и все с петли. Поднято на стенде и
# только на стенде; вернуть боевое число — строкой в окружении:
#   KORITSU_REGISTRATIONS_PER_IP_PER_DAY=5 web/e2e/stack.sh start
export KORITSU_REGISTRATIONS_PER_IP_PER_DAY="${KORITSU_REGISTRATIONS_PER_IP_PER_DAY:-1000}"
# Имя, на котором живёт админка: на всяком другом `/api/admin/*` отвечает 404.
# Стенд поднимает его нарочно, а не оставляет пустым, — так проверяется то же
# разделение, что и в бою. Значение — тот адрес, по которому стенд и смотрят
# (`127.0.0.1`); открыв тот же сайт как `localhost`, получаешь ровно то, что
# получит чужой снаружи: админки нет. Пустая строка выключает разделение.
export KORITSU_ADMIN_DOMAIN="${KORITSU_ADMIN_DOMAIN-$host}"
export FAKE_DELAY_MS="${FAKE_DELAY_MS:-30}"
export FAKE_CHUNK="${FAKE_CHUNK:-48}"

pidfile() { echo "$dir/$1.pid"; }
logfile() { echo "$dir/$1.log"; }

alive() {
  local f; f="$(pidfile "$1")"
  [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null
}

up() {
  local name="$1"; shift
  if alive "$name"; then
    echo "стенд: $name уже поднят (pid $(cat "$(pidfile "$name")"))"
    return 0
  fi
  "$@" >> "$(logfile "$name")" 2>&1 &
  echo $! > "$(pidfile "$name")"
  echo "стенд: $name поднят, pid $!, журнал $(logfile "$name")"
}

down() {
  local name="$1" f; f="$(pidfile "$name")"
  [ -f "$f" ] || return 0
  local p; p="$(cat "$f")"
  if kill -0 "$p" 2>/dev/null; then
    # SIGTERM, а не KILL: воркер по нему доделывает начатое задание, и стенд
    # останавливается тем же способом, каким останавливается боевой контейнер.
    kill "$p" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$p" 2>/dev/null || break
      sleep 0.2
    done
    kill -9 "$p" 2>/dev/null || true
    echo "стенд: $name остановлен (pid $p)"
  fi
  rm -f "$f"
}

wait_api() {
  local url="http://$host:$API_PORT/health"
  for _ in $(seq 1 100); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "стенд: служба отвечает — $url"
      return 0
    fi
    sleep 0.3
  done
  echo "стенд: служба не ответила за 30 с; хвост журнала:" >&2
  tail -n 30 "$(logfile serve)" >&2 || true
  return 1
}

wait_fake() {
  for _ in $(seq 1 50); do
    if curl -fsS "http://$host:$FAKE_PORT/health" >/dev/null 2>&1; then
      echo "стенд: поддельная модель отвечает — http://$host:$FAKE_PORT"
      return 0
    fi
    sleep 0.2
  done
  echo "стенд: поддельная модель не поднялась; хвост журнала:" >&2
  tail -n 20 "$(logfile fake-llm)" >&2 || true
  return 1
}

print_env() {
  cat <<EOS
export PYTHONPATH="$PYTHONPATH"
export KORITSU_DATA_DIR="$KORITSU_DATA_DIR"
export KORITSU_SECRET="$KORITSU_SECRET"
export KORITSU_ENV="$KORITSU_ENV"
export KORITSU_TRUST_PROXY="$KORITSU_TRUST_PROXY"
export KORITSU_BASE_URL="$KORITSU_BASE_URL"
export KORITSU_PROVIDER_KEY_DEEPSEEK="$KORITSU_PROVIDER_KEY_DEEPSEEK"
export KORITSU_LLM_BASE_URL_DEEPSEEK="$KORITSU_LLM_BASE_URL_DEEPSEEK"
export KORITSU_WORKER_POLL_S="$KORITSU_WORKER_POLL_S"
export KORITSU_REGISTRATIONS_PER_IP_PER_DAY="$KORITSU_REGISTRATIONS_PER_IP_PER_DAY"
export KORITSU_ADMIN_DOMAIN="$KORITSU_ADMIN_DOMAIN"
export API_PORT="$API_PORT"
export FAKE_PORT="$FAKE_PORT"
EOS
}

case "$cmd" in
  start)
    echo "$dir" > "$marker"
    echo "стенд: том $dir, служба $host:$API_PORT, модель $host:$FAKE_PORT"
    up fake-llm "$PYTHON" "$root/web/e2e/fake-llm/server.py" \
      --host "$host" --port "$FAKE_PORT"
    wait_fake
    # Миграция — до подъёма процессов и одним разом (см. `api/__main__.py`).
    "$PYTHON" -m api migrate | sed 's/^/стенд: /'
    up serve "$PYTHON" -m api serve --host "$host" --port "$API_PORT"
    up worker "$PYTHON" -m api worker
    wait_api
    echo "стенд: поднят. Остановить — web/e2e/stack.sh stop $dir"
    ;;
  wait)
    wait_fake && wait_api
    ;;
  stop)
    down worker
    down serve
    down fake-llm
    echo "стенд: остановлен, том остался — $dir"
    ;;
  status)
    echo "стенд: том $dir"
    for name in fake-llm serve worker; do
      if alive "$name"; then
        echo "  $name: жив (pid $(cat "$(pidfile "$name")")), журнал $(logfile "$name")"
      else
        echo "  $name: не поднят"
      fi
    done
    curl -fsS "http://$host:$API_PORT/health" 2>/dev/null \
      && echo "" || echo "  /health: не отвечает"
    ;;
  env)
    print_env
    ;;
  *)
    sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
