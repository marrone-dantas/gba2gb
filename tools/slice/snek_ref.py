"""Phase 5 B1: reference run of the original Snek GBA build in the headless mGBA
capturer (tools/gba_capture, binary at $MGBA_CAPTURE or /workspace/private/mgba_capture).

python -m tools.slice.snek_ref [OUTDIR]  ->  title / gameplay / death snapshots and
docs/img/snek_gba_ref.png (2x2 grid, 2x scale)."""
import os
import subprocess
import sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MGBA = os.environ.get("MGBA_CAPTURE", "/workspace/private/mgba_capture")
GBA = os.path.join(ROOT, "build", "snek", "snek.gba")
SCRIPT = """run 90
snap title
tap START
run 40
snap game_a
hold UP 20
run 25
snap game_b
hold LEFT 10
run 200
snap dead
"""
SHOTS = ["title", "game_a", "game_b", "dead"]


def build():
    subprocess.run(["make", "-s", "-f", os.path.join(ROOT, "tools", "slice", "Makefile.snek")], check=True)
    return GBA


def capture(outdir, script=SCRIPT):
    build()
    os.makedirs(outdir, exist_ok=True)
    sp = os.path.join(outdir, "script.txt")
    open(sp, "w").write(script)
    subprocess.run([MGBA, GBA, sp, outdir], check=True, capture_output=True)
    return {n: Image.open(os.path.join(outdir, n, "screen.ppm")).convert("RGB") for n in SHOTS if
            os.path.exists(os.path.join(outdir, n, "screen.ppm"))}


def grid(ims, path, scale=2):
    w, h = ims[0].size
    g = Image.new("RGB", (2 * w * scale, ((len(ims) + 1) // 2) * h * scale))
    for i, im in enumerate(ims):
        g.paste(im.resize((w * scale, h * scale), Image.NEAREST), ((i % 2) * w * scale, (i // 2) * h * scale))
    g.save(path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "snek", "mgba_ref")
    ims = capture(out)
    grid([ims[n] for n in SHOTS], os.path.join(ROOT, "docs", "img", "snek_gba_ref.png"))
    print("ok", list(ims))
