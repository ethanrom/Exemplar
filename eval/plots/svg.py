"""A tiny SVG writer for the static evaluation charts (no plotting dependency).

Chart conventions: 2px lines, markers >= 8 px with a 2px surface ring, hairline solid grid, text in ink tokens (never
in the series colour), a legend for two or more series, light and dark palettes selected through `prefers-color-scheme`, shapes
as a second identity channel.  The three series colours stay distinguishable from each other in both modes.
"""
from __future__ import annotations

from html import escape
from typing import Optional

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# series slots (light / dark); shape = the non-colour identity channel
SERIES = {
    "exemplar_a": {"var": "s1", "shape": "circle"},       # slot 1 blue   : Exemplar, more examples (k = max)
    "exemplar_b": {"var": "s2", "shape": "square"},       # slot 2 orange : Exemplar, fewer examples
    "zero_shot": {"var": "s3", "shape": "diamond"},       # slot 3 aqua   : zero-shot vision LLM
}

CSS = f"""
svg.exm {{ --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
          --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --warn:#d03b3b; font-family:{FONT}; }}
@media (prefers-color-scheme: dark) {{ svg.exm {{ --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a;
          --axis:#383835; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --warn:#ec835a; }} }}
svg.exm .bg {{ fill:var(--surface); }}
svg.exm text {{ fill:var(--ink2); font-size:12px; }}
svg.exm text.ink {{ fill:var(--ink); }}
svg.exm text.title {{ fill:var(--ink); font-size:16px; font-weight:600; }}
svg.exm text.sub {{ fill:var(--ink2); font-size:12px; }}
svg.exm text.muted {{ fill:var(--muted); font-size:11px; }}
svg.exm text.strong {{ fill:var(--ink); font-weight:600; }}
svg.exm .grid {{ stroke:var(--grid); stroke-width:1; fill:none; }}
svg.exm .axis {{ stroke:var(--axis); stroke-width:1; fill:none; }}
svg.exm .rule {{ stroke:var(--ink); stroke-width:1.5; fill:none; }}
svg.exm .s1 {{ fill:var(--s1); stroke:var(--s1); }} svg.exm .s2 {{ fill:var(--s2); stroke:var(--s2); }}
svg.exm .s3 {{ fill:var(--s3); stroke:var(--s3); }}
svg.exm .l1 {{ stroke:var(--s1); }} svg.exm .l2 {{ stroke:var(--s2); }} svg.exm .l3 {{ stroke:var(--s3); }}
svg.exm .ring {{ stroke:var(--surface); stroke-width:2; }}
svg.exm .hollow {{ fill:var(--surface); stroke-width:2; }}
svg.exm .span {{ stroke-width:2; stroke-linecap:round; fill:none; }}
svg.exm .faint {{ opacity:.45; stroke:none; }}
"""


def fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def text_width(s: str, size: float = 12) -> float:
    return 0.56 * size * len(s)


class Svg:
    def __init__(self, width: int, height: int, *, title: str, desc: str):
        self.w, self.h = width, height
        self.title, self.desc = title, desc
        self.parts: list[str] = []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x: float, y: float, s: str, *, cls: str = "", anchor: str = "start", size: Optional[float] = None,
             rotate: Optional[float] = None) -> None:
        extra = f' font-size="{size}"' if size else ""
        tr = f' transform="rotate({rotate} {fmt(x)} {fmt(y)})"' if rotate else ""
        c = f' class="{cls}"' if cls else ""
        self.add(f'<text x="{fmt(x)}" y="{fmt(y)}" text-anchor="{anchor}"{c}{extra}{tr}>{escape(s)}</text>')

    def line(self, x1: float, y1: float, x2: float, y2: float, cls: str = "grid") -> None:
        self.add(f'<line x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" y2="{fmt(y2)}" class="{cls}"/>')

    def rect(self, x: float, y: float, w: float, h: float, cls: str = "") -> None:
        self.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" class="{cls}"/>')

    def marker(self, shape: str, x: float, y: float, var: str, *, r: float = 5, hollow: bool = False, faint: bool = False) -> None:
        """A series marker (diameter >= 8) with the 2px surface ring; `hollow` = outline only (uncalibrated variants)."""
        cls = f"s{var[-1]}" + (" hollow" if hollow else " ring") + (" faint" if faint else "")
        if shape == "circle":
            self.add(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r)}" class="{cls}"/>')
        elif shape == "square":
            self.add(f'<rect x="{fmt(x - r)}" y="{fmt(y - r)}" width="{fmt(2 * r)}" height="{fmt(2 * r)}" rx="1" class="{cls}"/>')
        else:   # diamond
            d = r * 1.3
            self.add(f'<polygon points="{fmt(x)},{fmt(y - d)} {fmt(x + d)},{fmt(y)} {fmt(x)},{fmt(y + d)} {fmt(x - d)},{fmt(y)}" class="{cls}"/>')

    def hbar(self, x0: float, y: float, w: float, h: float, var: str, r: float = 4) -> None:
        """Horizontal bar growing from x0, square at the baseline, 4px rounded data end."""
        r = min(r, w, h / 2)
        self.add(f'<path d="M{fmt(x0)},{fmt(y)} H{fmt(x0 + w - r)} a{fmt(r)},{fmt(r)} 0 0 1 {fmt(r)},{fmt(r)} V{fmt(y + h - r)} '
                 f'a{fmt(r)},{fmt(r)} 0 0 1 {fmt(-r)},{fmt(r)} H{fmt(x0)} Z" class="s{var[-1]}" stroke="none"/>')

    def render(self) -> str:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" class="exm" role="img" aria-labelledby="t d" viewBox="0 0 {self.w} {self.h}" '
                f'width="{self.w}" height="{self.h}">\n<title id="t">{escape(self.title)}</title>\n<desc id="d">{escape(self.desc)}</desc>\n'
                f'<style>{CSS}</style>\n<rect class="bg" x="0" y="0" width="{self.w}" height="{self.h}"/>\n')
        return head + "\n".join(self.parts) + "\n</svg>\n"


def legend(svg: Svg, x: float, y: float, items: list[tuple[str, str, str, bool]], gap: float = 22) -> float:
    """Horizontal legend of (label, series var, shape, hollow); returns the x after the last item."""
    for label, var, shape, hollow in items:
        svg.marker(shape, x + 6, y - 4, var, r=4.5, hollow=hollow)
        svg.text(x + 18, y, label, cls="ink")
        x += 18 + text_width(label) + gap
    return x
