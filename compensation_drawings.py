"""Clean, code-native versions of the two legacy compensation references.

These are reference schematics, not newly designed compensation networks.
Connections and designators follow ``comp_images/opamp3.png`` and
``comp_images/tl431f.png``.  In particular the op-amp lower-divider resistor
is intentionally left unlabelled, as it is in that original reference.

Matplotlib is imported only when a drawing is requested.  Document builders
without Matplotlib can therefore use pre-generated resources instead.
"""

from io import BytesIO


class _Drawing:
    def __init__(self, ax):
        from matplotlib.patches import FancyArrowPatch, Polygon

        self.ax = ax
        self.Polygon = Polygon
        self.FancyArrowPatch = FancyArrowPatch
        self.ink = "#111111"
        self.width = 1.7

    def wire(self, *points, width=None):
        x, y = zip(*points)
        self.ax.plot(x, y, color=self.ink, lw=width or self.width,
                     solid_capstyle="round", solid_joinstyle="round")

    def text(self, x, y, label, **kwargs):
        kwargs.setdefault("fontsize", 17)
        kwargs.setdefault("ha", "center")
        kwargs.setdefault("va", "center")
        self.ax.text(x, y, label, color=self.ink, **kwargs)

    def node(self, x, y):
        self.ax.plot(x, y, "o", color=self.ink, ms=4)

    def terminal(self, x, y):
        self.ax.plot(x, y, "o", mfc="white", mec=self.ink, mew=1.7, ms=6)

    def ground(self, x, y, isolated=False):
        if isolated:
            self.wire((x - .30, y), (x, y - .27), (x + .30, y),
                      (x - .30, y))
        else:
            for dy, half_width in ((0, .31), (-.13, .21), (-.26, .11)):
                self.wire((x - half_width, y + dy),
                          (x + half_width, y + dy))

    def resistor(self, x, y, label=None, vertical=True,
                 length=1.05, label_xy=None):
        half, breadth = length / 2, .15
        if vertical:
            vertices = [(x - breadth, y - half), (x + breadth, y - half),
                        (x + breadth, y + half), (x - breadth, y + half)]
            ends = ((x, y - half), (x, y + half))
            label_xy = label_xy or (x + .57, y)
        else:
            vertices = [(x - half, y - breadth), (x + half, y - breadth),
                        (x + half, y + breadth), (x - half, y + breadth)]
            ends = ((x - half, y), (x + half, y))
            label_xy = label_xy or (x, y + .43)
        self.ax.add_patch(self.Polygon(vertices, closed=True, fill=False,
                                      edgecolor=self.ink, lw=self.width))
        if label:
            self.text(*label_xy, label)
        return ends

    def capacitor(self, x, y, label=None, vertical=True, label_xy=None):
        gap, half_width = .065, .32
        if vertical:
            self.wire((x - half_width, y - gap), (x + half_width, y - gap))
            self.wire((x - half_width, y + gap), (x + half_width, y + gap))
            ends = ((x, y - gap), (x, y + gap))
            label_xy = label_xy or (x + .65, y)
        else:
            self.wire((x - gap, y - half_width), (x - gap, y + half_width))
            self.wire((x + gap, y - half_width), (x + gap, y + half_width))
            ends = ((x - gap, y), (x + gap, y))
            label_xy = label_xy or (x, y + .55)
        if label:
            self.text(*label_xy, label)
        return ends

    def arrow(self, start, end, scale=14):
        self.ax.add_patch(self.FancyArrowPatch(
            start, end, arrowstyle="->", mutation_scale=scale,
            lw=self.width, color=self.ink, shrinkA=0, shrinkB=0))


def _opamp3(ax):
    """R1 || (R3+C3), and feedback C2 || (R2+C1), exactly as supplied."""
    s = _Drawing(ax)
    ax.set_xlim(-.05, 12.05)
    ax.set_ylim(-.02, 7.65)

    # V_o -> R1 -> summing node, with R3+C3 in parallel with R1.
    s.terminal(1.5, 6.95)
    s.text(1.5, 7.38, r"$V_o$")
    s.wire((1.5, 6.95), (1.5, 6.35), (3.6, 6.35), (3.6, 5.925))
    s.resistor(1.5, 4.75, r"$R_1$", label_xy=(.75, 4.75))
    s.wire((1.5, 6.35), (1.5, 5.275))
    s.wire((1.5, 4.225), (1.5, 3.05), (7.5, 3.05))
    s.resistor(3.6, 5.4, r"$R_3$", label_xy=(4.23, 5.4))
    s.capacitor(3.6, 4.05, r"$C_3$", label_xy=(4.23, 4.05))
    s.wire((3.6, 4.875), (3.6, 4.115))
    s.wire((3.6, 3.985), (3.6, 3.05))

    # The original reference includes an unlabelled lower-divider resistor.
    s.resistor(1.5, 1.60, length=.95)
    s.wire((1.5, 3.05), (1.5, 2.075))
    s.wire((1.5, 1.125), (1.5, .55))
    s.ground(1.5, .55)

    # R2+C1 and C2 both return from V_c to the same summing node.
    s.wire((5.6, 3.05), (5.6, 6.35), (8.135, 6.35))
    s.capacitor(8.2, 6.35, r"$C_2$", vertical=False)
    s.wire((8.265, 6.35), (10.4, 6.35), (10.4, 2.4))
    s.wire((5.6, 4.85), (6.175, 4.85))
    s.resistor(6.7, 4.85, r"$R_2$", vertical=False)
    s.wire((7.225, 4.85), (8.735, 4.85))
    s.capacitor(8.8, 4.85, r"$C_1$", vertical=False)
    s.wire((8.865, 4.85), (10.4, 4.85))

    # Ideal op amp: minus input is the divider/feedback summing node.
    ax.add_patch(s.Polygon([(7.5, 1.15), (7.5, 3.65), (9.65, 2.4)],
                          closed=True, fill=False,
                          edgecolor=s.ink, lw=s.width))
    s.text(7.76, 3.05, "−", fontsize=19)
    s.text(7.76, 1.75, "+", fontsize=19)
    s.wire((5.95, 1.75), (7.5, 1.75))
    s.terminal(5.95, 1.75)
    s.text(5.95, 1.22, r"$V_{REF}$")
    s.wire((9.65, 2.4), (11.35, 2.4))
    s.terminal(11.35, 2.4)
    s.text(11.35, 2.98, r"$V_c$")
    for x, y in ((1.5, 6.35), (1.5, 3.05), (3.6, 3.05),
                 (5.6, 3.05), (5.6, 4.85), (10.4, 4.85), (10.4, 2.4)):
        s.node(x, y)


def _tl431f(ax):
    """TL431 fast lane: Vout -> R_LED || (R_pz+C_pz) -> opto LED."""
    s = _Drawing(ax)
    ax.set_xlim(-.05, 12.2)
    ax.set_ylim(-.15, 9.65)
    primary_x, led_x, pz_x, divider_x = 3.2, 5.75, 7.55, 10.4
    top, led_top, cathode, feedback, bottom = 8.7, 5.45, 2.8, 1.75, .4

    # Optocoupler output: Vdd -> Rpullup -> collector; C2 to primary ground.
    s.terminal(primary_x, 9.1)
    s.text(primary_x, 9.49, r"$V_{dd}$")
    s.wire((primary_x, 9.1), (primary_x, 7.875))
    s.resistor(primary_x, 7.35, r"$R_{pullup}$",
               label_xy=(1.98, 7.35))
    s.wire((primary_x, 6.825), (primary_x, 4.8), (1.2, 4.8), (1.2, 2.565))
    s.capacitor(1.2, 2.5, r"$C_2$", label_xy=(.52, 2.5))
    s.wire((1.2, 2.435), (1.2, bottom), (primary_x, bottom))
    # Phototransistor symbol, without an electrical base connection.
    s.wire((primary_x, 4.8), (primary_x, 4.5), (3.57, 4.13))
    s.wire((3.57, 3.47), (primary_x, 3.05), (primary_x, bottom))
    s.wire((3.57, 3.45), (3.57, 4.15), width=3.2)
    s.arrow((3.42, 3.3), (primary_x, 3.05), scale=11)
    s.ground(primary_x, bottom)
    s.node(primary_x, 4.8)
    s.node(primary_x, bottom)

    # Secondary supply and LED/fast-lane parallel branches.
    s.terminal(divider_x, 9.1)
    s.text(divider_x, 9.49, r"$V_{out}$")
    s.wire((divider_x, 9.1), (divider_x, top), (led_x, top), (led_x, 7.875))
    s.resistor(led_x, 7.35, r"$R_{LED}$", label_xy=(4.72, 7.35))
    s.wire((led_x, 6.825), (led_x, led_top), (pz_x, led_top), (pz_x, 5.965))
    s.wire((pz_x, top), (pz_x, 7.875))
    s.resistor(pz_x, 7.35, r"$R_{pz}$", label_xy=(8.23, 7.35))
    s.wire((pz_x, 6.825), (pz_x, 6.095))
    s.capacitor(pz_x, 6.03, r"$C_{pz}$", label_xy=(8.31, 6.03))
    s.wire((led_x, led_top), (led_x, 4.42))

    # LED points down: anode at led_top, cathode at TL431 cathode node.
    ax.add_patch(s.Polygon([(led_x - .30, 4.08), (led_x + .30, 4.08),
                           (led_x, 3.56)], closed=True, fill=False,
                          edgecolor=s.ink, lw=s.width))
    s.wire((led_x, 4.42), (led_x, 4.08))
    s.wire((led_x - .34, 3.56), (led_x + .34, 3.56), width=3.2)
    s.wire((led_x, 3.56), (led_x, cathode))
    # Two optical arrows, not wires, couple the LED to the phototransistor.
    s.arrow((5.05, 4.12), (4.15, 4.12))
    s.arrow((5.05, 3.77), (4.15, 3.77))
    s.wire((led_x, led_top), (pz_x, led_top), (pz_x, 4.375))
    s.resistor(pz_x, 3.85, r"$R_{bias}$", label_xy=(8.32, 3.85))
    s.wire((pz_x, 3.325), (pz_x, cathode), (led_x, cathode))

    # Divider and C1 feedback, matching the supplied TL431 fast-lane figure.
    s.wire((divider_x, top), (divider_x, 7.875))
    s.resistor(divider_x, 7.35, r"$R_1$", label_xy=(11.09, 7.35))
    s.wire((divider_x, 6.825), (divider_x, feedback), (6.13, feedback))
    s.wire((led_x, cathode), (8.585, cathode))
    s.capacitor(8.65, cathode, r"$C_1$", vertical=False,
                label_xy=(8.65, 2.27))
    s.wire((8.715, cathode), (divider_x, cathode))
    s.resistor(divider_x, .94, r"$R_{lower}$", length=.70,
               label_xy=(11.37, .94))
    s.wire((divider_x, feedback), (divider_x, 1.29))
    s.wire((divider_x, .59), (divider_x, bottom), (led_x, bottom), (led_x, 1.3))

    # Three-terminal shunt regulator, with a separate reference input.
    ax.add_patch(s.Polygon([(led_x - .37, 1.3), (led_x + .37, 1.3),
                           (led_x, 2.12)], closed=True, fill=False,
                          edgecolor=s.ink, lw=s.width))
    s.wire((led_x, cathode), (led_x, 2.12))
    s.wire((led_x - .55, 1.93), (led_x - .37, 2.12),
           (led_x + .37, 2.12), (led_x + .55, 2.31))
    s.text(4.52, 1.59, "TL431", fontsize=14)
    s.ground(divider_x, bottom, isolated=True)
    for x, y in ((pz_x, top), (divider_x, top), (led_x, led_top),
                 (led_x, cathode), (pz_x, cathode), (divider_x, cathode),
                 (divider_x, feedback), (divider_x, bottom)):
        s.node(x, y)


def compensation_reference(kind):
    """Return a crisp PNG reference drawing as bytes.

    ``kind`` is ``'opamp3'`` or ``'tl431f'``.  No Matplotlib import happens
    until this function is called, and no pyplot/global figure is created.
    """
    if kind not in ("opamp3", "tl431f"):
        raise ValueError("Unsupported compensation reference: " + str(kind))
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    size = (10.6, 6.65) if kind == "opamp3" else (9.3, 7.5)
    figure = Figure(figsize=size, facecolor="white")
    FigureCanvasAgg(figure)
    ax = figure.add_axes((.025, .025, .95, .95))
    ax.set_aspect("equal")
    ax.set_axis_off()
    (_opamp3 if kind == "opamp3" else _tl431f)(ax)
    stream = BytesIO()
    figure.savefig(stream, format="png", dpi=220, facecolor="white")
    return stream.getvalue()


if __name__ == '__main__':
    from pathlib import Path
    import argparse
    from app_resources import resource_path
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default=str(resource_path('comp_images')))
    args=parser.parse_args()
    folder=Path(args.out);folder.mkdir(parents=True,exist_ok=True)
    for kind in ('opamp3','tl431f'):
        target=folder/(kind+'_clean.png')
        target.write_bytes(compensation_reference(kind))
        print(target.resolve())
