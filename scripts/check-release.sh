#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"

printf '==> Python syntax\n'
"$PYTHON_BIN" -m compileall -q ed_journal_probe.py src/elite_journal_helper

printf '==> Tests\n'
"$PYTHON_BIN" -m pytest -q

printf '==> Git whitespace check\n'
git diff --check

printf '==> Version\n'
"$PYTHON_BIN" ed_journal_probe.py --version

printf '==> Root Python files\n'
ROOT_PY_COUNT="$(find . -maxdepth 1 -type f -name '*.py' -printf '%f\n' | wc -l)"
if [[ "$ROOT_PY_COUNT" -ne 1 ]] || [[ ! -f ed_journal_probe.py ]]; then
  echo "Expected only ed_journal_probe.py at the repository root."
  find . -maxdepth 1 -type f -name '*.py' -printf '  %f\n'
  exit 1
fi

printf '==> Release checks passed\n'
