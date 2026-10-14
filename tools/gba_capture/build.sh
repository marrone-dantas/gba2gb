#!/bin/sh
# Build mgba_capture against a libmgba 0.10 source tree built with cmake (static lib).
# usage: tools/gba_capture/build.sh MGBA_SRC_DIR OUT
M=$1
gcc -O2 -o "$2" "$(dirname "$0")/mgba_capture.c" -I"$M/include" -I"$M/build/include" -DM_CORE_GBA \
    "$M/build/libmgba.a" -lm -lpthread /usr/lib/x86_64-linux-gnu/libz.so.1
