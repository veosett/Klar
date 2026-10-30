#!/bin/sh
# Klar without Python (docs/ROADMAP.md, item 33): from a seed compiler to a working klarc, on a machine with no Python.
#
#   KLARC=/path/to/seed/klarc sh tests/no_python.sh
#
# Builds klarc from the seed (build.sh), checks the formatting of the repository, type-checks and tests the examples
# and the tools, then uses the one built file outside the repository, as someone who has only downloaded it.
set -e
cd "$(dirname "$0")/.."
if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
  echo "error: this check needs a machine without Python" >&2
  exit 1
fi
sh ./build.sh
K="$(pwd)/build/klarc"
LIB="--lib $(pwd)/klar"

"$K" fmt --check . $LIB
for f in compiler/klarc.klar examples/*.klar tools/*.klar; do
  [ "$f" = examples/mistakes.klar ] && continue     # its errors are the point
  "$K" check "$f" $LIB >/dev/null || { echo "error: klarc check $f" >&2; exit 1; }
done
tested=0
for f in examples/*.klar tools/*.klar; do
  if grep -q '^test "\|^property "' "$f"; then
    "$K" test "$f" -q $LIB >/dev/null || { echo "error: klarc test $f" >&2; exit 1; }
    tested=$((tested + 1))
  fi
done
echo "ok: $tested files with tests pass"

# the file alone: the runtime and the standard library are inside it
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
cp "$K" "$out/klarc"
cd "$out"
./klarc new demo >/dev/null
cd demo
../klarc dev main.klar >/dev/null
../klarc build main.klar -o demo >/dev/null
./demo >/dev/null
../klarc eval 'read_file("main.klar").is_ok()' | grep -q '^true : Bool$'
../klarc spec | grep -q '^## Std modules$'
echo "ok: no Python needed"
