"""Generate the MATTA bottle logo as a self-contained SVG.

Usage:  python scripts/make_logo.py path/to/oswald-latin-700-normal.woff2
        (pip install fonttools brotli; Oswald is SIL OFL, from @fontsource/oswald.
        Oswald Bold was picked over Anton, Bebas Neue and League Gothic: it is
        the closest to the hand-drawn original and its A keeps an open counter.)

Writes assets/logo.svg (black) and assets/logo-white.svg.

The design: the word MATTA in a heavy condensed face, stretched to fill a
bottle lying on its side, then clipped to the bottle's outline so the
letters' outer edges ARE the bottle. The last A runs into the shoulder;
the neck and cap sit after it, with a gap before the cap. Letters are
converted to paths, so the SVG needs no font.

Every shape is a parameter below, so the logo can be refined by editing
numbers and re-running.
"""

import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent

# ---- geometry (SVG units) -------------------------------------------------
W, H = 398, 170
BODY_X0 = 6                     # bottle base (left)
TOP, BOTTOM = 10, 160           # body top and bottom
BASE_R = 28                     # rounded base corners
SHOULDER_X0 = 288               # at the last A's peak, so its right side is the slope
NECK_X0, NECK_X1 = 328, 350     # neck
NECK_TOP, NECK_BOTTOM = 60, 110
GAP = 4                         # white gap between neck and lip
LIP_X1 = 362                    # lip ring, a little taller than the neck
LIP_TOP, LIP_BOTTOM = 54, 116
CAP_X1 = 392                    # cap flares out a little towards the open end
CAP_IN_TOP, CAP_IN_BOTTOM = 60, 110
CAP_OUT_TOP, CAP_OUT_BOTTOM = 55, 115
LETTER_GAP = 5                  # white gap between letters
LETTER_X1 = NECK_X0             # the last A ends where the neck starts
OVERSHOOT = 10                  # letters run past the body so the clip makes the edge
WORD = "MATTA"


def bottle_path():
    """Body + shoulder + neck as one closed outline (the clip)."""
    x0, t, b, r = BODY_X0, TOP, BOTTOM, BASE_R
    s0, n0, nt, nb = SHOULDER_X0, NECK_X0, NECK_TOP, NECK_BOTTOM
    # A long S-shaped shoulder: leaves the body flat, ends level into the neck.
    k1, k2 = (n0 - s0) * 0.55, (n0 - s0) * 0.45
    return (f"M{x0 + r},{t} H{s0} "
            f"C{s0 + k1},{t} {n0 - k2},{nt} {n0},{nt} "
            f"H{NECK_X1} V{nb} H{n0} "
            f"C{n0 - k2},{nb} {s0 + k1},{b} {s0},{b} "
            f"H{x0 + r} C{x0 + r * 0.25},{b} {x0},{b - r * 0.6} {x0},{(t + b) / 2} "
            f"C{x0},{t + r * 0.6} {x0 + r * 0.25},{t} {x0 + r},{t} Z")


def letters_path(font_file):
    font = TTFont(font_file)
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    glyphs = [cmap[ord(ch)] for ch in WORD]
    bounds = []
    for g in glyphs:
        from fontTools.pens.boundsPen import BoundsPen
        bp = BoundsPen(gs)
        gs[g].draw(bp)
        bounds.append(bp.bounds)       # (xMin, yMin, xMax, yMax)
    cap = font["OS/2"].sCapHeight
    # Vertical: cap height spans the body plus the overshoot on each side.
    y_top, y_bottom = TOP - OVERSHOOT, BOTTOM + OVERSHOOT
    sy = (y_bottom - y_top) / cap
    # Horizontal: glyph ink widths scaled to fill the run with fixed gaps.
    inks = [b[2] - b[0] for b in bounds]
    run = (LETTER_X1 - (BODY_X0 - OVERSHOOT)) - LETTER_GAP * (len(glyphs) - 1)
    sx = run / sum(inks)
    x = BODY_X0 - OVERSHOOT
    parts = []
    for g, (xmin, _, xmax, _) in zip(glyphs, bounds):
        pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        # font units (y up) -> SVG (y down); baseline sits on y_bottom
        tp = TransformPen(pen, (sx, 0, 0, -sy, x - xmin * sx, y_bottom))
        gs[g].draw(tp)
        parts.append(pen.getCommands())
        x += (xmax - xmin) * sx + LETTER_GAP
    return " ".join(parts)


def svg(font_file, fill):
    lip_x0 = NECK_X1 + GAP
    cap = (f"M{LIP_X1},{CAP_IN_TOP} L{CAP_X1 - 3},{CAP_OUT_TOP} Q{CAP_X1},{CAP_OUT_TOP} {CAP_X1},{CAP_OUT_TOP + 3} "
           f"V{CAP_OUT_BOTTOM - 3} Q{CAP_X1},{CAP_OUT_BOTTOM} {CAP_X1 - 3},{CAP_OUT_BOTTOM} "
           f"L{LIP_X1},{CAP_IN_BOTTOM} Z")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t">
  <title id="t">Matta</title>
  <defs>
    <clipPath id="bottle"><path d="{bottle_path()}"/></clipPath>
  </defs>
  <g fill="{fill}">
    <path clip-path="url(#bottle)" d="{letters_path(font_file)}"/>
    <rect x="{NECK_X0}" y="{NECK_TOP}" width="{NECK_X1 - NECK_X0}" height="{NECK_BOTTOM - NECK_TOP}"/>
    <rect x="{lip_x0}" y="{LIP_TOP}" width="{LIP_X1 - lip_x0}" height="{LIP_BOTTOM - LIP_TOP}" rx="2"/>
    <path d="{cap}"/>
  </g>
</svg>
'''


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    font_file = sys.argv[1]
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "logo.svg").write_text(svg(font_file, "#111111"), encoding="utf-8")
    (ROOT / "assets" / "logo-white.svg").write_text(svg(font_file, "#FFFFFF"), encoding="utf-8")
    print("Wrote assets/logo.svg and assets/logo-white.svg")


if __name__ == "__main__":
    main()
