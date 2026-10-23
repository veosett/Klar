#!/bin/sh
# Builds klarc (the Klar compiler written in Klar) without Python.
#
#   ./build.sh                 uses ./seed/klarc-<target>, $KLARC, or downloads the seed of this version's release
#   KLARC=/path/to/klarc ./build.sh
#
# The seed compiles compiler/klarc.klar into build/klarc1; klarc1 compiles it again into build/klarc. Both must be the
# same bytes (the compiler reproduces itself), so the result does not depend on where the seed came from.
set -e
cd "$(dirname "$0")"
case "$(uname -s)-$(uname -m)" in
  Darwin-*) TARGET=macos ;;           # experimental: an x86-64 executable, not yet tested on a Mac
  *-aarch64|*-arm64) TARGET=linux-arm64 ;;
  *) TARGET=linux ;;
esac
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
SEED=${KLARC:-seed/klarc-$TARGET}
if [ ! -x "$SEED" ]; then
  URL="https://github.com/veosett/Klar/releases/download/v$VERSION/klarc-$TARGET"
  echo "downloading the seed compiler: $URL"
  mkdir -p seed
  if command -v curl >/dev/null 2>&1; then curl -fsSL -o "$SEED" "$URL"; else wget -q -O "$SEED" "$URL"; fi
  chmod +x "$SEED"
fi
mkdir -p build
"$SEED" build compiler/klarc.klar -o build/klarc1 --target "$TARGET" --lib klar
build/klarc1 build compiler/klarc.klar -o build/klarc --target "$TARGET" --lib klar
if ! cmp -s build/klarc1 build/klarc; then
  echo "error: klarc does not reproduce itself (build/klarc1 != build/klarc)" >&2
  exit 1
fi
rm build/klarc1
echo "ok: build/klarc (KLAR_LIB=$(pwd)/klar)"
