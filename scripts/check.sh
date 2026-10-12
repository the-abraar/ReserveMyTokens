#!/usr/bin/env bash
# One command for all checks. Usage: scripts/check.sh [--fast]  (--fast = lint + stray files only)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
FAST=0; [ "${1:-}" = "--fast" ] && FAST=1

PY=${PYTHON:-}
[ -z "$PY" ] && PY=$(command -v python3.11 || command -v python3.12 || true)
[ -z "$PY" ] && { echo "Python 3.11 or 3.12 required (set \$PYTHON); 3.14 breaks scipy and others" >&2; exit 1; }
VENV=${CHECK_VENV:-$HOME/.cache/ReserveMyTokens-check-venv}

NAMES=(); RESULTS=()
step() { # name cmd...
  local n=$1; shift
  echo "=== $n"
  if "$@"; then RESULTS+=(pass); else RESULTS+=(FAIL); fi
  NAMES+=("$n")
}

setup_venv() {
  [ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q -r backend/requirements-dev.txt ruff "click>=8" "requests>=2.25" 2>&1 | tail -3
}
stray() { ! find . \( -name node_modules -o -name .venv -o -name .git -o -name .next -o -name build \) -prune -o \
  -type f \( -name '*-e' -o -name '*.orig' -o -name '*.rej' -o -name '*.bak' \) -print | grep .; }
banned() { # claims retired after provider-terms research
  ! grep -n -i -E 'unused AI subscription|share your subscription|API key pooling|Network is Live' README.md landing-page/index.html
}
pytest_both() { # dir; worker has no test extra, so it runs from source via PYTHONPATH
  (cd "$1" && export PYTHONPATH="$ROOT/worker/src" && "$VENV/bin/pytest" -q && "$VENV/bin/pytest" -q $(ls tests/test_*.py | sort -r))
}

step "venv" setup_venv
step "ruff" "$VENV/bin/ruff" check backend worker/src worker/tests
step "stray-files" stray
step "retired-claims" banned
step "unsafe-html" scripts/lint-innerhtml.sh
if [ $FAST = 0 ]; then
  step "backend-tests+reverse" pytest_both backend
  step "worker-tests+reverse" pytest_both worker
  step "web-lint" bash -c 'cd web && npm run lint'
  step "web-build" bash -c 'cd web && npm run build'
fi

echo; printf '%-26s | %s\n' step result; printf -- '---------------------------+-------\n'
rc=0
for i in "${!NAMES[@]}"; do printf '%-26s | %s\n' "${NAMES[$i]}" "${RESULTS[$i]}"; [ "${RESULTS[$i]}" = FAIL ] && rc=1; done
exit $rc
