"""Contact sheet of all dataset scenes (dumper composites)."""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw
from .snapshot import load
from .vram_scene_dumper import dump


def sheet(dirn, out, cols=4):
    names = sorted(f[:-4] for f in os.listdir(dirn) if f.endswith(".npz"))
    rows = (len(names) + cols - 1) // cols
    im = Image.new("RGB", (cols * 248, rows * 174), (30, 30, 30))
    d = ImageDraw.Draw(im)
    for i, n in enumerate(names):
        c = dump(load(os.path.join(dirn, n + ".npz")))["composite"]
        x, y = (i % cols) * 248 + 4, (i // cols) * 174 + 12
        im.paste(Image.fromarray(c), (x, y))
        d.text((x, y - 11), n, fill=(255, 255, 255))
    im.save(out)
    return names


if __name__ == "__main__":
    sheet(sys.argv[1], sys.argv[2])
