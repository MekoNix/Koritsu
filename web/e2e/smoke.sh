#!/usr/bin/env bash
# smoke.sh — путь человека по стенду одним curl'ом: от регистрации до текста тега.
#
#     web/e2e/stack.sh start /tmp/стенд
#     web/e2e/smoke.sh /tmp/стенд
#
# Каталог тома — аргумент или `/tmp/koritsu-e2e-last` (его пишет `stack.sh`).
# Порт службы — `API_PORT` (умолч. 8006).
#
# Что этим проверяется и чего не проверяет ни один тест службы. Тесты `tests/api`
# ходят `TestClient`'ом в том же процессе и подменяют провод модели; здесь всё
# настоящее и всё врозь: HTTP через сокет, cookie сессии и заслон CSRF в
# браузерном виде, очередь с подпроцессом задания, слой `llm` по сети до
# поддельного сервера, поток SSE. Ломается склейка именно тут — и до сайта
# доходит уже сломанной.
#
# Шагов тринадцать, каждый печатается; первое же расхождение роняет скрипт с
# кодом 1 и печатает, что пришло. Проверка идёт под свежим человеком (email с
# отметкой времени), поэтому её можно гонять по стенду сколько угодно раз.
#
# Имена переменных латиницей — bash не признаёт кириллицу в именах (см. stack.sh).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
marker="/tmp/koritsu-e2e-last"
dir="${1:-${KORITSU_E2E_DIR:-}}"
if [ -z "$dir" ] && [ -f "$marker" ]; then dir="$(cat "$marker")"; fi
if [ -z "$dir" ] || [ ! -d "$dir" ]; then
  echo "проверка: не найден том стенда; подними его — web/e2e/stack.sh start" >&2
  exit 2
fi

API_PORT="${API_PORT:-8006}"
BASE="http://127.0.0.1:$API_PORT"
PYTHON="${PYTHON:-$root/.venv/bin/python}"

work="$(mktemp -d /tmp/koritsu-smoke-XXXXXX)"
jar="$work/cookies"
body="$work/body.json"
trap 'rm -rf "$work"' EXIT

step_n=0
step() { step_n=$((step_n + 1)); printf '\n[%d] %s\n' "$step_n" "$1"; }
die() { printf 'ПРОВАЛ: %s\n' "$1" >&2; [ -s "$body" ] && head -c 800 "$body" >&2 && echo >&2; exit 1; }

# `code` возвращается отдельно от тела: `curl -f` прячет тело отказа, а нам
# нужен и код, и `error.code` из тела — сайт показывает свой текст именно по нему.
api() {
  local method="$1" path="$2" data="${3:-}"
  local csrf; csrf="$(awk '$6=="koritsu_csrf"{print $7}' "$jar" 2>/dev/null | tail -1)"
  local -a args=(-sS -o "$body" -w '%{http_code}' -b "$jar" -c "$jar"
                 -X "$method" "$BASE$path")
  if [ -n "$csrf" ]; then args+=(-H "X-CSRF-Token: $csrf"); fi
  if [ -n "$data" ]; then
    args+=(-H "Content-Type: application/json" --data-binary "$data")
  fi
  curl "${args[@]}"
}

# Достать поле из ответа. `python`, а не `grep`: значения бывают с кириллицей и
# экранированием, и вытащенное регуляркой имя тега однажды окажется не тем.
field() { "$PYTHON" -c 'import json,sys
из=json.load(open(sys.argv[1]))
for имя in sys.argv[2].split("."):
    из = из.get(имя) if isinstance(из, dict) else None
print("" if из is None else из)' "$body" "$1"; }

# ── 1. служба жива ───────────────────────────────────────────────────────────
step "служба отвечает: GET /health"
code="$(api GET /health)"
[ "$code" = "200" ] || die "/health ответил $code (стенд поднят?)"
echo "    $(cat "$body")"

# ── 2. регистрация ───────────────────────────────────────────────────────────
email="проба-$(date +%s)-$$@example.org"
password="Пароль-стенда-2026"
# Ник обязателен и уникален без учёта регистра — берём его из почты,
# она здесь и так одноразовая.
nickname="${email%%@*}"
step "регистрация: POST /api/auth/register ($email, ник $nickname)"
code="$(api POST /api/auth/register "$(printf '{"email":%s,"password":%s,"nickname":%s}' \
  "\"$email\"" "\"$password\"" "\"$nickname\"")")"
[ "$code" = "201" ] || die "регистрация ответила $code"
echo "    $(cat "$body")"

# ── 3. ссылка из письма ──────────────────────────────────────────────────────
# В `dev` письма не уходят никуда, а печатаются в журнал (`accounts.mail`
# ConsoleMailer). Журнал службы — единственное место, где эту ссылку берёт и
# разработчик; отдельной «ручки для тестов» у службы нет и заводить её нельзя.
step "токен подтверждения из журнала службы ($dir/serve.log)"
token=""
for _ in $(seq 1 20); do
  token="$(grep -o 'confirm?token=[A-Za-z0-9._-]*' "$dir/serve.log" 2>/dev/null \
           | tail -1 | cut -d= -f2)"
  [ -n "$token" ] && break
  sleep 0.3
done
[ -n "$token" ] || die "в журнале нет ссылки подтверждения"
echo "    token ${token:0:12}… (${#token} знаков)"

step "подтверждение почты: POST /api/auth/confirm"
code="$(api POST /api/auth/confirm "$(printf '{"token":"%s"}' "$token")")"
[ "$code" = "200" ] || die "подтверждение ответило $code"
echo "    $(cat "$body")"

# ── 4. вход ──────────────────────────────────────────────────────────────────
step "вход: POST /api/auth/login (cookie сессии и cookie CSRF)"
code="$(api POST /api/auth/login "$(printf '{"email":%s,"password":%s}' \
  "\"$email\"" "\"$password\"")")"
[ "$code" = "200" ] || die "вход ответил $code"
csrf="$(awk '$6=="koritsu_csrf"{print $7}' "$jar" | tail -1)"
[ -n "$csrf" ] || die "не выдана cookie CSRF — изменяющие запросы не пройдут"
echo "    вошли, CSRF ${csrf:0:8}…"

# ── 5. проект с шаблоном ─────────────────────────────────────────────────────
step "личное пространство: GET /api/workspaces/personal"
code="$(api GET /api/workspaces/personal)"
[ "$code" = "200" ] || die "личное пространство ответило $code"
ws="$(field id)"
echo "    пространство $ws"

step "проект с шаблоном (теги {{цель}} и {{выводы}}): POST /api/projects"
"$PYTHON" - "$work/шаблон.docx" <<'PY'
"""Шаблон, по которому служба строит манифест: два тега и заголовок."""
import sys
from docx import Document

документ = Document()
документ.add_paragraph("Отчёт по практике")
for ключ in ("цель", "выводы"):
    документ.add_paragraph("{{%s}}" % ключ)
документ.save(sys.argv[1])
PY
code="$(curl -sS -o "$body" -w '%{http_code}' -b "$jar" -c "$jar" \
  -H "X-CSRF-Token: $csrf" -F "workspace_id=$ws" -F "name=Стенд сайта" \
  -F "template=@$work/шаблон.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  "$BASE/api/projects")"
[ "$code" = "201" ] || die "создание проекта ответило $code"
project="$(field id)"
echo "    проект $project"

# ── 6. прогон модели ─────────────────────────────────────────────────────────
step "задание fill_tag на тег «цель»: POST /api/jobs"
code="$(api POST /api/jobs "$(printf '{"kind":"fill_tag","project_id":"%s","payload":{"key":"цель","endpoint":"deepseek"}}' "$project")")"
[ "$code" = "202" ] || die "постановка задания ответила $code"
job="$(field id)"
echo "    задание $job, состояние $(field status)"

step "поток задания до конца: GET /api/jobs/$job/stream"
# `--max-time`: поток закрывается сам по финалу задания, но если задание
# зависнет, проверка обязана упасть по времени, а не висеть до утра.
curl -sS -N --max-time 120 -b "$jar" -c "$jar" \
  "$BASE/api/jobs/$job/stream" > "$work/stream.txt" || true
events="$(grep '^event:' "$work/stream.txt" | sed 's/^event: *//' | tr '\n' ' ')"
echo "    события: $events"
grep -q '^event: *done' "$work/stream.txt" \
  || { cp "$work/stream.txt" "$body"; die "в потоке нет события done"; }
grep -q '^event: *text' "$work/stream.txt" \
  || { cp "$work/stream.txt" "$body"; die "в потоке нет кусков текста модели"; }

step "карточка задания: GET /api/jobs/$job"
code="$(api GET "/api/jobs/$job")"
[ "$code" = "200" ] || die "карточка задания ответила $code"
state="$(field status)"
[ "$state" = "done" ] || die "задание кончилось как $state"
echo "    состояние $state, ключ $(field result.key_source), версия $(field result.version)"

# ── 7. значение тега ─────────────────────────────────────────────────────────
step "значения проекта: GET /api/projects/$project/values"
code="$(api GET "/api/projects/$project/values")"
[ "$code" = "200" ] || die "значения ответили $code"
value_text="$("$PYTHON" -c 'import json,sys
значения=json.load(open(sys.argv[1]))["values"]
цель=значения.get("цель") or {}
print((цель.get("text") or "").replace("\n"," ")[:160])' "$body")"
[ -n "$value_text" ] || die "тег «цель» пуст — прогон ничего не записал"
echo "    цель: $value_text"
case "$value_text" in
  *поддельн*) : ;;
  *) die "в значении нет следа поддельной модели — прогон сходил не туда?" ;;
esac

# ── 8. беда по требованию ────────────────────────────────────────────────────
step "маркер [[FAKE:500]] соседним значением → задание должно упасть"
# Маркер уезжает в промпт соседом (`prompt.neighbors_part`): другого способа
# передать его модели с сайта нет, а нам нужно проверить именно то, как служба
# показывает беду прогона.
code="$(api PUT "/api/projects/$project/values/выводы" \
  '{"type":"markdown","text":"[[FAKE:500]]"}')"
[ "$code" = "200" ] || die "запись значения рукой ответила $code"
code="$(api POST /api/jobs "$(printf '{"kind":"fill_tag","project_id":"%s","payload":{"key":"цель","endpoint":"deepseek","overwrite":true}}' "$project")")"
[ "$code" = "202" ] || die "постановка задания с маркером ответила $code"
bad_job="$(field id)"
curl -sS -N --max-time 120 -b "$jar" -c "$jar" \
  "$BASE/api/jobs/$bad_job/stream" > "$work/stream-err.txt" || true
code="$(api GET "/api/jobs/$bad_job")"
state="$(field status)"
[ "$state" = "failed" ] || die "задание с маркером кончилось как $state"
echo "    состояние $state, беда $(field error.code) — $(field error.message)"

# ── 9. остаток ───────────────────────────────────────────────────────────────
step "расход: GET /api/usage"
code="$(api GET /api/usage)"
[ "$code" = "200" ] || die "расход ответил $code"
echo "    $(head -c 300 "$body")"

printf '\nПРОВЕРКА ПРОЙДЕНА: %d шагов, том %s\n' "$step_n" "$dir"
