#!/usr/bin/env bash
#
# dev-up.sh — bring up the whole midsphere local stack so the notebooks work
#             out of the box.
#
#   ./dev-up.sh          start everything; block until Ctrl+C (which stops it all)
#   ./dev-up.sh stop     stop everything this script started
#
# What it starts:
#   - Postgres (exo-postgres) + Redis (sukuna-redis) containers
#   - a cloudflared tunnel -> backend  (so the cloud sandbox can POST callbacks +
#     proxied tool/knowledge requests back to you)
#   - the Django backend (ASGI, :8010) and the Astro dashboard (:4321)
#   - the example developer endpoints (examples/example_endpoints.py, :9099) +
#     a second cloudflared tunnel, so the custom-tool / knowledge demos in the
#     notebook reach a real, public endpoint
#   - writes examples/midsphere.env (API key, URLs) that the notebooks read
#
# Why two tunnels: cloudflared quick tunnels are free + need no account/API key,
# and the E2B sandbox can only reach PUBLIC URLs — localhost is unreachable.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/packages/backend"
FRONTEND="$ROOT/packages/frontend"
EXAMPLES="$ROOT/examples"
ENV_FILE="$BACKEND/.env"
NB_ENV="$EXAMPLES/midsphere.env"
LOG="/tmp/midsphere"
mkdir -p "$LOG"

PG_CONTAINER="exo-postgres"
REDIS_CONTAINER="sukuna-redis"
BACKEND_PORT=8010
FRONTEND_PORT=4321
TOOL_PORT=9099

green() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
red()   { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }

stop_all() {
  pkill -f "cloudflared tunnel --url http://localhost:$BACKEND_PORT" 2>/dev/null || true
  pkill -f "cloudflared tunnel --url http://localhost:$TOOL_PORT"    2>/dev/null || true
  pkill -f "uvicorn config.asgi"                                     2>/dev/null || true
  pkill -f "astro dev"                                               2>/dev/null || true
  pkill -f "example_endpoints.py"                                    2>/dev/null || true
  for f in cf_backend cf_tool backend frontend toolsrv; do
    [ -f "$LOG/$f.pid" ] && { kill "$(cat "$LOG/$f.pid")" 2>/dev/null || true; rm -f "$LOG/$f.pid"; }
  done
}

if [ "${1:-up}" = "stop" ] || [ "${1:-up}" = "down" ]; then
  green "Stopping midsphere stack..."; stop_all; green "Stopped."; exit 0
fi

# ---- preflight --------------------------------------------------------------
for bin in cloudflared uv docker node; do
  command -v "$bin" >/dev/null || { red "$bin not installed (see README prerequisites)."; exit 1; }
done
trap 'echo; green "Shutting down..."; stop_all; green "Stopped."; exit 0' INT TERM
stop_all; sleep 1

# ---- 1. infra ---------------------------------------------------------------
green "Ensuring Postgres ($PG_CONTAINER) + Redis ($REDIS_CONTAINER)..."
docker start "$PG_CONTAINER" >/dev/null 2>&1 \
  || docker run -d --name "$PG_CONTAINER" -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
       -p 5432:5432 postgres:16 >/dev/null 2>&1 \
  || { red "could not start Postgres ($PG_CONTAINER) — is Docker running?"; exit 1; }
docker start "$REDIS_CONTAINER" >/dev/null 2>&1 \
  || docker run -d --name "$REDIS_CONTAINER" -p 6379:6379 redis:7-alpine >/dev/null
until docker exec "$PG_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec "$PG_CONTAINER" psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='sukuna_headless'" \
  2>/dev/null | grep -q 1 \
  || docker exec "$PG_CONTAINER" psql -U postgres -c "CREATE DATABASE sukuna_headless" >/dev/null 2>&1 || true
green "Postgres + Redis ready."

# ---- 2. cloudflared tunnels (backend callbacks + example endpoints) ---------
start_tunnel() {  # start_tunnel <port> <logname> -> echoes the https url
  local port="$1" name="$2" url=""
  nohup cloudflared tunnel --url "http://localhost:$port" --no-autoupdate > "$LOG/$name.log" 2>&1 &
  echo $! > "$LOG/$name.pid"
  for _ in $(seq 1 30); do
    url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG/$name.log" | head -1)"
    [ -n "$url" ] && break; sleep 1
  done
  echo "$url"
}
green "Starting cloudflared tunnel -> backend :$BACKEND_PORT ..."
BACKEND_TUNNEL="$(start_tunnel "$BACKEND_PORT" cf_backend)"
[ -z "$BACKEND_TUNNEL" ] && { red "backend tunnel failed (see $LOG/cf_backend.log)"; stop_all; exit 1; }
green "Backend tunnel: $BACKEND_TUNNEL"

# ---- 3. example developer endpoints + their tunnel -------------------------
green "Starting example endpoints :$TOOL_PORT (custom tool + knowledge source)..."
nohup python3 "$EXAMPLES/example_endpoints.py" > "$LOG/toolsrv.log" 2>&1 &
echo $! > "$LOG/toolsrv.pid"
EXAMPLE_TUNNEL="$(start_tunnel "$TOOL_PORT" cf_tool)"
[ -z "$EXAMPLE_TUNNEL" ] && { red "example tunnel failed"; stop_all; exit 1; }
green "Example endpoint tunnel: $EXAMPLE_TUNNEL"

# ---- 4. write tunnel + hosts into the backend .env -------------------------
set_env() {
  local k="$1" v="$2"
  if grep -q "^${k}=" "$ENV_FILE"; then sed -i "s|^${k}=.*|${k}=${v}|" "$ENV_FILE"
  else printf '%s=%s\n' "$k" "$v" >> "$ENV_FILE"; fi
}
set_env BACKEND_PUBLIC_URL "$BACKEND_TUNNEL"
set_env ALLOWED_HOSTS '["localhost","127.0.0.1",".trycloudflare.com"]'

# ---- 5. backend: migrate, seed, serve --------------------------------------
green "Migrating + seeding the demo account..."
( cd "$BACKEND" && uv run manage.py migrate --no-input >"$LOG/migrate.log" 2>&1 ) \
  || { red "migrations failed (see $LOG/migrate.log)"; stop_all; exit 1; }
SEED_OUT="$(cd "$BACKEND" && uv run manage.py shell < "$ROOT/scripts/seed_demo.py" 2>/dev/null)"
API_KEY="$(echo "$SEED_OUT" | grep -oE 'SEED_API_KEY=.*' | cut -d= -f2-)"
[ -z "$API_KEY" ] && { red "seed did not return an API key"; stop_all; exit 1; }

green "Starting backend on :$BACKEND_PORT ..."
( cd "$BACKEND" && nohup uv run uvicorn config.asgi:application --host 127.0.0.1 --port "$BACKEND_PORT" \
    > "$LOG/backend.log" 2>&1 & echo $! > "$LOG/backend.pid" )
for _ in $(seq 1 30); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$BACKEND_PORT/graphql/" \
      -H 'content-type: application/json' -d '{"query":"{ health }"}' 2>/dev/null)" = "200" ] && break
  sleep 1
done
green "Backend up."

# ---- 6. frontend dashboard --------------------------------------------------
green "Starting frontend on :$FRONTEND_PORT ..."
( cd "$FRONTEND" && API_URL="http://localhost:$BACKEND_PORT" CLIENT_API_URL="http://localhost:$BACKEND_PORT" \
    nohup npm run dev > "$LOG/frontend.log" 2>&1 & echo $! > "$LOG/frontend.pid" )
for _ in $(seq 1 45); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$FRONTEND_PORT/login" 2>/dev/null)" = "200" ] && break
  sleep 1
done
green "Frontend up."

# ---- 7. examples venv (SDK + jupyter) --------------------------------------
if [ ! -x "$EXAMPLES/.venv/bin/python" ] || ! "$EXAMPLES/.venv/bin/python" -c "import midsphere" 2>/dev/null; then
  green "Setting up examples venv (SDK + Jupyter) — first run only..."
  ( cd "$EXAMPLES" && uv venv .venv >/dev/null 2>&1 \
      && uv pip install --python .venv -e ../packages/sdk-py jupyterlab ipykernel e2b httpx python-dotenv nbformat >"$LOG/venv.log" 2>&1 \
      && .venv/bin/python -m ipykernel install --user --name midsphere --display-name "Midsphere SDK" >/dev/null 2>&1 ) \
      || red "examples venv setup hit an issue (see $LOG/venv.log) — notebook may need manual install"
fi

# ---- 8. config the notebooks read ------------------------------------------
E2B_KEY="$(grep -E '^E2B_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
cat > "$NB_ENV" <<EOF
# Auto-generated by dev-up.sh — the notebooks load this. Do not commit.
MIDSPHERE_API_KEY=$API_KEY
MIDSPHERE_BASE_URL=http://localhost:$BACKEND_PORT
MIDSPHERE_EXAMPLE_ENDPOINT=$EXAMPLE_TUNNEL
E2B_API_KEY=$E2B_KEY
EOF
green "Wrote $NB_ENV"

# ---- summary ----------------------------------------------------------------
cat <<EOF

============================================================
  midsphere local stack is UP  (everything for the notebooks)
------------------------------------------------------------
  Dashboard   : http://localhost:$FRONTEND_PORT
                login: demo@midsphere.local / demo12345
  Backend     : http://localhost:$BACKEND_PORT
  Backend tun : $BACKEND_TUNNEL   (sandbox callbacks + tool/knowledge proxy)
  Example tun : $EXAMPLE_TUNNEL   (the notebook's custom tool + knowledge source)
  API key     : $API_KEY
  Notebook cfg: $NB_ENV

  Run the notebooks:
    cd examples && .venv/bin/jupyter lab     # open midsphere_*.ipynb

  Press Ctrl+C to stop everything.   (or: ./dev-up.sh stop)
============================================================
EOF

wait
