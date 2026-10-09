#!/usr/bin/env bash
# Run a command. If it fails, publish the end of its output as a GitHub error annotation,
# so the failure can be read from the run page (and the public API) without downloading logs.
#
#   bash .github/scripts/run-and-annotate.sh "<step title>" <command> [args...]
set -uo pipefail

title="$1"
shift
log="$(mktemp)"

"$@" 2>&1 | tee "$log"
status=${PIPESTATUS[0]}

if [ "$status" -ne 0 ]; then
  # Annotation messages are one line: encode % and newlines as GitHub expects.
  body="$(grep -v '^[[:space:]]*$' "$log" | tail -n 60 | sed 's/%/%25/g; s/\r//g' |
    awk 'BEGIN { ORS = "%0A" } { print }')"
  echo "::error title=${title} failed::${body}"
fi
rm -f "$log"
exit "$status"
