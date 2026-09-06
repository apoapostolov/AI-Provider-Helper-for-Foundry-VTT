#!/usr/bin/env bash
# Linux launcher for the AI helper. Leave the window open while you play.
set -u
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
  py=python3
elif command -v python >/dev/null 2>&1; then
  py=python
else
  echo "Python 3 not found. Install python3 and retry." >&2
  if [ -t 0 ]; then
    read -r -p "Press Enter to close "
  fi
  exit 1
fi

"$py" ./run-helper.py "$@"
code=$?
if [ "$code" -ne 0 ] && [ -t 0 ]; then
  read -r -p "Press Enter to close "
fi
exit "$code"
