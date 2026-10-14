"""Side-by-side screenshots: GBA reference render (left) | PyBoy DMG screen (right)."""
from PIL import Image, ImageDraw


def side_by_side(gba_img, gb_img, path, scale=2, title=None):
    w = gba_img.width + gb_img.width + 8
    h = max(gba_img.height, gb_img.height) + 12
    out = Image.new("RGB", (w, h), (40, 40, 40))
    out.paste(gba_img, (0, 12))
    out.paste(gb_img.convert("RGB"), (gba_img.width + 8, 12))
    d = ImageDraw.Draw(out)
    d.text((2, 0), "GBA reference (Unicorn)", fill=(255, 255, 255))
    d.text((gba_img.width + 10, 0), "GB DMG (PyBoy, transpiled)" if title is None else title, fill=(255, 255, 255))
    out = out.resize((w * scale, h * scale), Image.NEAREST)
    out.save(path)
