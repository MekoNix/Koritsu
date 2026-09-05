#!/usr/bin/env bash
# stack-fg.sh — тот же стенд, но на переднем плане: для `webServer` Playwright.
#
#     API_PORT=8000 FAKE_PORT=8010 bash web/e2e/stack-fg.sh <каталог тома>
#
# Зачем отдельный скрипт. `stack.sh start` поднимает три процесса и выходит —
# а `webServer` Playwright ждёт живую команду и считает вышедшую упавшей.
# Поэтому здесь: поднять стенд, ждать, и по сигналу остановки погасить его тем
# же `stack.sh stop`. Иначе после прогона на машине оставались бы служба,
# воркер и поддельная модель.
#
# Имена переменных латиницей — bash не признаёт кириллицу в именах (см. stack.sh).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dir="${1:-${KORITSU_E2E_DIR:-}}"
if [ -z "$dir" ]; then
  echo "стенд: не назван каталог тома" >&2
  exit 2
fi

остановить() {
  bash "$here/stack.sh" stop "$dir" || true
  exit 0
}
trap остановить INT TERM

bash "$here/stack.sh" start "$dir"

# Ждём сигнала. `sleep` короткий: обработчик сигнала в bash срабатывает не
# посреди команды, а после неё, и минутный сон задержал бы остановку на минуту.
while :; do
  sleep 1
done
