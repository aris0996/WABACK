#!/bin/sh
set -eu

NO_CACHE=""
SKIP_START="false"

for arg in "$@"; do
  case "$arg" in
    --no-cache) NO_CACHE="--no-cache" ;;
    --skip-start) SKIP_START="true" ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

step() {
  percent="$1"
  title="$2"
  detail="${3:-}"
  printf "\n\033[36m[%3s%%] %s\033[0m\n" "$percent" "$title"
  if [ -n "$detail" ]; then
    printf "      \033[90m%s\033[0m\n" "$detail"
  fi
}

ok() {
  printf "      \033[32mOK: %s\033[0m\n" "$1"
}

warn() {
  printf "      \033[33mWARN: %s\033[0m\n" "$1"
}

run() {
  printf "      \033[90m> %s\033[0m\n" "$*"
  "$@"
}

STARTED="$(date +%s)"

printf "WhatsApp AI Memory Bot - Docker Build\n"
printf "\033[90mMode log: detail/plain, cocok untuk melihat proses build di terminal.\033[0m\n"

step 5 "Cek Docker"
run docker version
run docker compose version
ok "Docker dan Docker Compose tersedia."

step 15 "Cek file environment"
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    warn ".env belum ada, dibuat dari .env.example. Ganti secret sebelum production."
  else
    echo ".env dan .env.example tidak ditemukan."
    exit 1
  fi
else
  ok ".env ditemukan."
fi

step 25 "Validasi docker-compose.yml"
run docker compose config
ok "Konfigurasi Compose valid."

step 40 "Build image Docker" "Log layer Docker ditampilkan lengkap."
run docker compose build --progress=plain $NO_CACHE
ok "Build image selesai."

if [ "$SKIP_START" = "false" ]; then
  step 75 "Start container"
  run docker compose up -d
  ok "Container dijalankan."

  step 88 "Tampilkan status container"
  run docker compose ps

  step 95 "Log awal aplikasi" "Menampilkan 80 baris log terakhir."
  run docker compose logs --tail=80
else
  step 95 "Skip start container"
  warn "Build selesai, container tidak dijalankan karena parameter --skip-start."
fi

ENDED="$(date +%s)"
DURATION="$((ENDED - STARTED))"

step 100 "Selesai"
printf "      \033[32mDurasi: %ss\033[0m\n" "$DURATION"
printf "      \033[32mDashboard: http://localhost:5000\033[0m\n"
printf "      \033[32mJika port host diubah, pakai http://IP_SERVER:PORT\033[0m\n"
