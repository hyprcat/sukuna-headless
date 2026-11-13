#!/usr/bin/env bash
set -euo pipefail

# Smoke test for the local Docker Compose stack.
# Verifies backend, frontend, and infrastructure are up and functional.
#
# Usage:
#   ./scripts/smoke-test.sh
#   ./scripts/smoke-test.sh --backend-url http://api.example.com --frontend-url http://app.example.com

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:4321}"
TIMEOUT=5
PASS=0
FAIL=0
SKIP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-url)
      [[ $# -ge 2 ]] || { echo "--backend-url requires a value" >&2; exit 2; }
      BACKEND_URL="$2"
      shift 2
      ;;
    --frontend-url)
      [[ $# -ge 2 ]] || { echo "--frontend-url requires a value" >&2; exit 2; }
      FRONTEND_URL="$2"
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || { echo "--timeout requires a value" >&2; exit 2; }
      TIMEOUT="$2"
      shift 2
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

check() {
  local name="$1"
  shift
  if "$@"; then
    PASS=$((PASS + 1))
    printf "  \033[32mPASS\033[0m %s\n" "$name"
  else
    FAIL=$((FAIL + 1))
    printf "  \033[31mFAIL\033[0m %s\n" "$name"
  fi
}

skip() {
  local name="$1"
  local reason="$2"
  SKIP=$((SKIP + 1))
  printf "  \033[33mSKIP\033[0m %s (skipped: %s)\n" "$name" "$reason"
}

http_status() {
  local method="$1"
  local url="$2"
  local data="${3:-}"
  local code
  if [[ "$method" == "POST" ]]; then
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" -X POST -H "Content-Type: application/json" -d "$data" "$url" 2>/dev/null) || true
  else
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$url" 2>/dev/null) || true
  fi
  echo "${code:-000}"
}

http_ok() {
  local status
  status=$(http_status GET "$1")
  test "${status:0:1}" = "2"
}

status_in() {
  local status="$1"
  shift
  for code in "$@"; do
    if [[ "$status" == "$code" ]]; then
      return 0
    fi
  done
  return 1
}

json_field() {
  local url="$1"
  local field="$2"
  local expected="$3"
  local body
  body=$(curl -s --max-time "$TIMEOUT" "$url" 2>/dev/null) || return 1
  echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('$field')=='$expected' else 1)" 2>/dev/null
}

admin_static_loads() {
  local html asset asset_url status
  html=$(curl -fsS --max-time "$TIMEOUT" "$BACKEND_URL/admin/login/" 2>/dev/null) || return 1
  asset=$(printf "%s" "$html" | python3 -c '
from html.parser import HTMLParser
import sys


class StaticAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.asset = ""

    def handle_starttag(self, tag, attrs):
        if self.asset:
            return
        values = dict(attrs)
        candidate = values.get("href") or values.get("src") or ""
        if "/static/" in candidate or candidate.startswith("static/"):
            self.asset = candidate


parser = StaticAssetParser()
parser.feed(sys.stdin.read())
print(parser.asset)
' 2>/dev/null) || return 1
  [[ -n "$asset" ]] || return 1
  if [[ "$asset" =~ ^https?:// ]]; then
    asset_url="$asset"
  elif [[ "$asset" == /* ]]; then
    asset_url="${BACKEND_URL%/}$asset"
  else
    asset_url="${BACKEND_URL%/}/$asset"
  fi
  status=$(http_status GET "$asset_url")
  status_in "$status" 200 304
}

graphql_introspect() {
  local url="$1/graphql/"
  local payload='{"query":"{ __schema { queryType { name } } }"}'
  local resp
  resp=$(curl -s --max-time "$TIMEOUT" -X POST -H "Content-Type: application/json" -d "$payload" "$url" 2>/dev/null) || return 1
  echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('data',{}).get('__schema') else 1)" 2>/dev/null
}

db_query_via_compose() {
  docker compose exec -T backend python -m django shell -c "
from django.contrib.auth import get_user_model
from django.db import connection

connection.ensure_connection()
print(get_user_model().objects.count())
" >/dev/null 2>&1
}

echo ""
echo "Smoke test - backend=$BACKEND_URL  frontend=$FRONTEND_URL"
echo ""

# Backend health
echo "Backend:"
check "Health endpoint (GET /healthz)" json_field "$BACKEND_URL/healthz" "status" "ok"
check "Readiness probe (GET /readyz)" json_field "$BACKEND_URL/readyz" "status" "ready"

# Migrations
echo ""
echo "Migrations:"
if docker compose ps --services 2>/dev/null | grep -q backend; then
  UNAPPLIED=$(docker compose exec -T backend python -m django showmigrations --plan 2>/dev/null | grep -c "\[ \]" || true)
  if [[ "$UNAPPLIED" == "0" ]]; then
    check "All migrations applied" true
  else
    check "All migrations applied ($UNAPPLIED unapplied)" false
  fi
else
  skip "All migrations applied" "docker compose not running"
fi

if docker compose ps --services 2>/dev/null | grep -q backend; then
  check "Database-backed Django query" db_query_via_compose
else
  skip "Database-backed Django query" "docker compose not running"
fi

# Admin
echo ""
echo "Admin:"
ADMIN_STATUS=$(http_status GET "$BACKEND_URL/admin/login/")
check "Admin login page (GET /admin/login/ -> $ADMIN_STATUS)" status_in "$ADMIN_STATUS" 200 302
check "Admin static asset loads" admin_static_loads

# GraphQL
echo ""
echo "GraphQL:"
check "Schema introspection (POST /graphql/)" graphql_introspect "$BACKEND_URL"

# Auth endpoints
echo ""
echo "Auth:"
LOGIN_STATUS=$(http_status POST "$BACKEND_URL/auth/login/" '{}')
check "Login endpoint rejects empty POST (POST /auth/login/ -> $LOGIN_STATUS)" status_in "$LOGIN_STATUS" 400

# Webhook endpoint
echo ""
echo "Webhooks:"
DODO_STATUS=$(http_status POST "$BACKEND_URL/webhooks/dodo/" '{}')
check "Dodo webhook rejects unsigned POST (-> $DODO_STATUS)" status_in "$DODO_STATUS" 400

# Frontend
echo ""
echo "Frontend:"
check "Login page (GET /login)" http_ok "$FRONTEND_URL/login"
check "Signup page (GET /signup)" http_ok "$FRONTEND_URL/signup"

DASH_STATUS=$(http_status GET "$FRONTEND_URL/dashboard")
check "Dashboard (GET /dashboard -> $DASH_STATUS)" status_in "$DASH_STATUS" 200 302 303

# Summary
echo ""
TOTAL=$((PASS + FAIL + SKIP))
if [[ $FAIL -eq 0 ]]; then
  printf "\033[32m%d/%d passed\033[0m" "$PASS" "$TOTAL"
else
  printf "\033[31m%d/%d passed, %d failed\033[0m" "$PASS" "$TOTAL" "$FAIL"
fi
if [[ $SKIP -gt 0 ]]; then
  printf ", %d skipped" "$SKIP"
fi
echo ""
echo ""

exit "$FAIL"
