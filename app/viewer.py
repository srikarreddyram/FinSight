"""Render a filing page as PNG with the cited passage highlighted (the source-viewer panel)."""

from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path

_MD_NOISE = re.compile(r"[|#*`]+|-{3,}")


def _phrases(snippet: str, max_phrases: int = 8) -> list[str]:
    """Short, distinctive phrases from the cited chunk that are likely to be found verbatim on the page."""
    out: list[str] = []
    for line in snippet.splitlines():
        line = _MD_NOISE.sub(" ", line)
        cells = [c.strip() for c in re.split(r"\s{2,}", line) if c.strip()] or [line.strip()]
        for cell in cells:
            words = cell.split()
            if len(words) < 3 or line.startswith("Table:"):
                continue
            out.append(" ".join(words[:7]))
            if len(out) >= max_phrases:
                return out
    return out


@lru_cache(maxsize=32)
def _open(path: str):
    import pdfplumber

    return pdfplumber.open(path)


def render_page(pdf_path: Path, page: int, snippet: str = "", resolution: int = 110, full_rows: bool = False) -> bytes:
    pdf = _open(str(pdf_path))
    page = max(1, min(page, len(pdf.pages)))
    p = pdf.pages[page - 1]
    img = p.to_image(resolution=resolution)
    rects = []
    for phrase in _phrases(snippet):
        try:
            rects += p.search(phrase, regex=False, case=False)
        except Exception:  # noqa: BLE001 - highlighting is best effort
            continue
    if rects:
        right = p.width * 0.93  # table rows: carry the highlight across to the value columns
        img.draw_rects(
            [(r["x0"] - 2, r["top"] - 2, (right if full_rows else r["x1"]) + 2, r["bottom"] + 2) for r in rects],
            fill=(255, 214, 0, 70),
            stroke=(230, 160, 0),
            stroke_width=1,
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def page_count(pdf_path: Path) -> int:
    return len(_open(str(pdf_path)).pages)
