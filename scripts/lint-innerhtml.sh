#!/usr/bin/env bash
# Fails on HTML sinks fed by template interpolation, concatenation, or an opening multi-line template.
# Allow with `// safe-html: <reason>` on the same line or the line directly above.
set -uo pipefail
cd "$(dirname "$0")/.."
sink='(innerHTML|outerHTML|insertAdjacentHTML|document\.write|dangerouslySetInnerHTML)'
files=$(find . \( -name node_modules -o -name .git -o -name .next -o -name build -o -name dist -o -name .venv \) -prune -o \
  -type f \( -name '*.html' -o -name '*.js' -o -name '*.jsx' -o -name '*.ts' -o -name '*.tsx' \) ! -name '*.d.ts' ! -name '*.min.js' -print)
[ -z "$files" ] && exit 0
# shortcut: line-based grep, misses sinks whose argument starts on a later line; upgrade to an AST lint if code grows.
hits=$(echo "$files" | xargs awk -v sink="$sink" '
  { if ($0 ~ sink && ($0 ~ /\$\{/ || $0 ~ /`[[:space:]]*$/ || $0 ~ /["'"'"'][[:space:]]*\+|\+[[:space:]]*["'"'"']/) \
      && $0 !~ /safe-html:/ && prev !~ /safe-html:/) printf "%s:%d: %s\n", FILENAME, FNR, $0
    prev = $0 }')
if [ -n "$hits" ]; then echo "$hits"; echo "unsafe HTML sinks found (add '// safe-html: <reason>' if justified)"; exit 1; fi
