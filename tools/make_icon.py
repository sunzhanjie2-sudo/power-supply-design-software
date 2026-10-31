"""Generate the application icon (icon.png for the source GUI, icon.ico for
the PyInstaller build).  Run once:  python make_icon.py
"""
import os

from PIL import Image, ImageDraw

SIZE = 256


def make_icon():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # rounded-rect background with a vertical blue gradient
    r = 56
    d.rounded_rectangle([6, 6, SIZE - 6, SIZE - 6], radius=r,
                        fill=(13, 71, 161, 255))
    top, bot = (25, 97, 190), (10, 55, 130)
    for y in range(24, SIZE - 24):
        t = y / (SIZE - 48)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        d.line([(24, y), (SIZE - 24, y)], fill=c + (255,))

    # white power symbol: stem + arc
    w = 16
    d.line([(SIZE / 2, 62), (SIZE / 2, 150)], fill=(255, 255, 255, 255),
           width=w)
    d.arc([SIZE / 2 - 58, SIZE / 2 - 58, SIZE / 2 + 58, SIZE / 2 + 58],
          start=130, end=410, fill=(255, 255, 255, 255), width=w)

    # small switch-mode waveform accent at the bottom
    pts = [(58, 208), (86, 208), (86, 192), (114, 192), (114, 208),
           (142, 208), (142, 192), (170, 192), (170, 208), (198, 208)]
    d.line(pts, fill=(255, 255, 255, 220), width=9, joint='curve')

    # sine-wave accent under the power symbol
    pts2 = []
    cx, cy, amp, wdt = 128, 230, 16, 150
    import math
    for i in range(wdt + 1):
        x = cx - wdt / 2 + i
        y = cy + amp * math.sin(2 * math.pi * i / wdt)
        pts2.append((x, y))
    d.line(pts2, fill=(255, 255, 255, 160), width=7, joint='curve')

    # glossy highlight
    d.rounded_rectangle([18, 14, SIZE - 18, 84], radius=40,
                        fill=(255, 255, 255, 26))

    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'icons')
    os.makedirs(here, exist_ok=True)
    img.save(os.path.join(here, 'icon.png'))
    img.save(os.path.join(here, 'icon.ico'),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                    (128, 128), (256, 256)])
    print('icon.png / icon.ico written to', here)


if __name__ == '__main__':
    make_icon()
