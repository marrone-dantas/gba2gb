#!/usr/bin/env bash
# Instala o toolchain da Fase 0: venv Python, arm-none-eabi-gcc e RGBDS.
set -euo pipefail
cd "$(dirname "$0")/.."
RGBDS_VER="${RGBDS_VER:-v1.0.4}"

if ! command -v arm-none-eabi-gcc >/dev/null; then
  sudo apt-get update && sudo apt-get install -y gcc-arm-none-eabi
fi

if ! command -v rgbasm >/dev/null; then
  if ! (sudo apt-get install -y rgbds 2>/dev/null); then
    # Release binária oficial (gbdev/rgbds)
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/rgbds.tar.xz" \
      "https://github.com/gbdev/rgbds/releases/download/${RGBDS_VER}/rgbds-linux-x86_64.tar.xz"
    # python em vez de tar -J: a box pode não ter xz-utils
    python3 -c "import tarfile,sys;tarfile.open(sys.argv[1]).extractall(sys.argv[2],filter='data')" "$tmp/rgbds.tar.xz" "$tmp"
    sudo install -m755 "$tmp"/rgbasm "$tmp"/rgblink "$tmp"/rgbfix "$tmp"/rgbgfx /usr/local/bin/
  fi
fi

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "Toolchain OK: $(arm-none-eabi-gcc --version | head -1); $(rgbasm -V)"
