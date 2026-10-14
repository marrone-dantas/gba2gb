# mgba_capture: headless GBA snapshot capture

`mgba_capture.c` drives libmgba (0.10) headlessly from a small text script: run frames,
hold/tap keys, poke memory, save/load states, and dump VRAM/palette/IO/OAM in the
snapshot directory format (docs/vq_snapshot_format.md) together with the emulator's
rendered frame (`screen.ppm`). Commands are listed at the top of the source file.

Build (libmgba from source, no frontends needed):

    git clone --depth 1 --branch 0.10.5 https://github.com/mgba-emu/mgba.git
    cd mgba && mkdir build && cd build
    cmake .. -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DBUILD_QT=OFF -DBUILD_SDL=OFF -DUSE_FFMPEG=OFF \
      -DUSE_LIBZIP=OFF -DUSE_MINIZIP=OFF -DUSE_PNG=OFF -DUSE_SQLITE3=OFF -DUSE_ELF=OFF -DUSE_LUA=OFF \
      -DUSE_EDITLINE=OFF -DUSE_DISCORD_RPC=OFF -DENABLE_SCRIPTING=OFF -DBUILD_STATIC=ON -DBUILD_SHARED=OFF \
      -DM_CORE_GB=OFF -DUSE_EPOXY=OFF -DBUILD_GL=OFF -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF -DUSE_DEBUGGERS=OFF
    make mgba
    tools/gba_capture/build.sh /path/to/mgba ./mgba_capture

Evaluate captured scenes with `python -m tools.vq.eval_scenes MANIFEST --out DIR`.
Keep ROMs, states and captures outside the repository (see .gitignore).
