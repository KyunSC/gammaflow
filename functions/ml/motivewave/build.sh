#!/bin/bash
# Build the MotiveWave "IV Wall Break" strategy.
#   ./build.sh            compile, run the logic checks, write build/ivwall.jar
#   ./build.sh install    also copy the jar into ~/MotiveWave Extensions (restart MotiveWave afterwards)
set -euo pipefail
cd "$(dirname "$0")"
SDK="${MWAVE_SDK:-/Applications/MotiveWave.app/Contents/Java/mwave_sdk.jar}"
EXT="${MWAVE_EXT:-$HOME/MotiveWave Extensions}"
[ -f "$SDK" ] || { echo "MotiveWave SDK jar not found at $SDK (set MWAVE_SDK)"; exit 1; }

rm -rf build
mkdir -p build/classes build/test
javac --release 17 -Xlint:all,-auxiliaryclass -Werror -cp "$SDK" -d build/classes src/ivwall/*.java
javac --release 17 -cp build/classes -d build/test test/ivwall/*.java
java -cp build/classes:build/test ivwall.IvWallLogicTest
jar --create --file build/ivwall.jar -C build/classes .
echo "built build/ivwall.jar"

if [ "${1:-}" = "install" ]; then
  mkdir -p "$EXT"
  cp build/ivwall.jar "$EXT/ivwall.jar"
  touch "$EXT/.last_updated"
  echo "installed to $EXT/ivwall.jar (restart MotiveWave to load it)"
fi
