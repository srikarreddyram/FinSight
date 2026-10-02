"""Parse filing PDFs into ordered elements (headings, text, tables) with page numbers and sections.

Docling is the primary parser (reading order + table structure). pdfplumber is the fallback when
Docling fails or returns suspiciously little text. `pypdf` is the naive baseline for ablation run A.
Parsed output is cached as JSON under data/parsed/<parser>/<doc_id>.json so it is computed once.

    uv run python -m ingest.parse --doc 3M_2018_10K
    uv run python -m ingest.parse --all
"""

from __future__ import annotations

import argparse
import logging
import re
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.schemas import DocMeta, Element, ParsedDoc

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------------
# Section classification
# --------------------------------------------------------------------------------------------

# (pattern, section) pairs checked in order against heading text. 10-Q item numbers differ from 10-K
# ones, so those are handled separately in classify_heading.
_SECTION_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bitem\s*1a\b|\brisk\s+factors\b|\brisk\s+management\b|\bkey\s+risks\b", re.I), "Risk Factors"),
    (re.compile(r"\bitem\s*7a\b|quantitative and qualitative disclosures? about market risk", re.I), "Market Risk"),
    (re.compile(r"\bitem\s*7\b|management'?s?\s+discussion|management discussion|operating and financial review", re.I), "MD&A"),
    (re.compile(r"\bnotes?\s+to\s+(the\s+)?(consolidated\s+|standalone\s+|condensed\s+)*financial\s+statements", re.I), "Notes"),
    (
        re.compile(r"report of independent registered|independent auditor'?s'? report|auditor'?s'? report", re.I),
        "Auditor's Report",
    ),
    (re.compile(r"\bitem\s*8\b|financial statements and supplementary data", re.I), "Financial Statements"),
    (re.compile(r"\bitem\s*9a\b|controls and procedures", re.I), "Controls"),
    (
        re.compile(
            r"\bitem\s*1[0-4]\b|directors,? executive officers|executive compensation|corporate governance|board'?s'? report|directors'? report",
            re.I,
        ),
        "Governance",
    ),
    (re.compile(r"\bitem\s*5\b|market for (the )?registrant", re.I), "Market for Equity"),
    (re.compile(r"\bitem\s*3\b|legal proceedings", re.I), "Legal Proceedings"),
    (re.compile(r"\bitem\s*2\b|^properties$", re.I), "Properties"),
    (re.compile(r"\bitem\s*1\b(?!\s*[0-9a-z])|^business$|business overview", re.I), "Business"),
    (re.compile(r"business responsibility|sustainability report|\besg\b", re.I), "Sustainability"),
    (re.compile(r"question[- ]and[- ]answer|q\s*&\s*a session", re.I), "Q&A"),
    (re.compile(r"prepared remarks|opening remarks", re.I), "Prepared Remarks"),
]
# Headings that start a primary financial statement. These don't pull us out of the Notes section,
# because notes contain their own "balance sheet" style sub-headings.
_STATEMENT = re.compile(
    r"(consolidated|standalone|condensed)?\s*(statements?|balance sheets?)\s+of\s+(income|operations|earnings|cash flows?|"
    r"financial (position|condition)|comprehensive|changes in|stockholders|shareholders|profit and loss)|"
    r"^(consolidated|standalone|condensed)[\w\s]*balance sheets?|^balance sheets?$",
    re.I,
)
_10Q_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bitem\s*1a\b|risk factors", re.I), "Risk Factors"),
    (re.compile(r"\bitem\s*2\b|management'?s?\s+discussion", re.I), "MD&A"),
    (re.compile(r"\bitem\s*3\b|market risk", re.I), "Market Risk"),
    (re.compile(r"\bitem\s*4\b|controls and procedures", re.I), "Controls"),
    (re.compile(r"\bitem\s*1\b(?!\s*[0-9a-z])|financial statements", re.I), "Financial Statements"),
]


_20F_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bitem\s*3\b|risk factors|key information", re.I), "Risk Factors"),
    (re.compile(r"\bitem\s*4\b|information on the company", re.I), "Business"),
    (re.compile(r"\bitem\s*5\b|operating and financial review", re.I), "MD&A"),
    (re.compile(r"\bitem\s*(6|7|10|16[a-z]?)\b|directors|major shareholders", re.I), "Governance"),
    (re.compile(r"\bitem\s*(8|17|18)\b|financial information|financial statements", re.I), "Financial Statements"),
    (re.compile(r"\bitem\s*11\b|market risk", re.I), "Market Risk"),
    (re.compile(r"\bitem\s*15\b|controls and procedures", re.I), "Controls"),
    (re.compile(r"\bitem\s*19\b|exhibits", re.I), "Exhibits"),
]
_10K_EXTRA: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bitem\s*6\b|selected financial data", re.I), "Selected Financial Data"),
    (re.compile(r"\bitem\s*15\b|exhibits", re.I), "Exhibits"),
    (re.compile(r"\bitem\s*(1b|1c|4|9|9b|9c|16)\b", re.I), "Other"),
]
_ITEM = re.compile(r"^\W*(part\s+[iv]+\W+)?item\s*\d+[a-z]?\b", re.I)
_NOTES = _SECTION_RULES[3][0]
_NOTE_N = re.compile(r"^\W*note\s+1?\d\b", re.I)  # "Note 1. Description of Business" opens the notes
_AUDITOR = _SECTION_RULES[4][0]


def classify_heading(heading: str, current: str, doc_type: str) -> str:
    """Return the canonical section a heading starts, or `current` if it doesn't start one.

    SEC filings are organised by "Item N" headings, and sub-headings inside an item (a "Legal
    Proceedings" note, a "Risk management" paragraph in MD&A) must not move us to another section.
    So for 10-K/10-Q only Item headings, statement titles, the notes header and the auditor's report
    switch sections. Other documents (annual reports, transcripts) use the keyword rules directly.
    """
    h = " ".join(heading.split())[:200]
    if not h:
        return current
    if doc_type in ("10-K", "10-Q", "20-F"):
        if _ITEM.search(h):
            rules = {"10-Q": _10Q_RULES, "20-F": _20F_RULES}.get(doc_type, _10K_EXTRA + _SECTION_RULES)
            for pat, section in rules:
                if pat.search(h):
                    return section
            return "Other"
        if _NOTES.search(h) or (current == "Financial Statements" and _NOTE_N.match(h)):
            return "Notes"
        if _AUDITOR.search(h):
            return "Auditor's Report"
        if current not in ("Notes", "Controls", "Governance") and _STATEMENT.search(h):
            return "Financial Statements"
        return current
    if current != "Notes" and _STATEMENT.search(h):
        return "Financial Statements"
    for pat, section in _SECTION_RULES:
        if pat.search(h):
            return section
    return current


_SHORT_WORDS = {
    "a",
    "an",
    "am",
    "as",
    "at",
    "be",
    "by",
    "co",
    "do",
    "go",
    "he",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "no",
    "of",
    "on",
    "or",
    "so",
    "to",
    "up",
    "us",
    "vs",
    "we",
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "x",
    "ok",
    "id",
}
_SPLIT_LOWER = re.compile(r"\b([A-Za-z]{3,}) ([a-z]{1,2})\b(?=[\s.,;:)]|$)")
_SPLIT_UPPER = re.compile(r"\b([A-Z]{3,}) ([A-Z]{1,2})\b")
_SPLIT_APOS = re.compile(r"(\w)['’] s\b")


def fix_kerning(text: str) -> str:
    """Re-join words that PDF text extraction split with a stray space ("Cash Flow s", "LIQUIDI TY", "Registrant' s")."""
    text = _SPLIT_APOS.sub(r"\1's", text)
    text = _SPLIT_LOWER.sub(lambda m: m.group(0) if m.group(2).lower() in _SHORT_WORDS else m.group(1) + m.group(2), text)
    return _SPLIT_UPPER.sub(lambda m: m.group(0) if m.group(2).lower() in _SHORT_WORDS else m.group(1) + m.group(2), text)


_ITEM_LINE = re.compile(r"^\W*(?:part\s+[iv]+\W+)?item\s*(\d+[a-z]?)\s*[.:\-–—]", re.I)


def _looks_like_item_heading(line: str) -> bool:
    """'Item 7. Management's Discussion...' yes; a wrapped sentence '...see Part II, Item 8. Financial
    Statements of this Annual Report. We' no."""
    m = _ITEM_LINE.match(line)
    if not m or len(line) > 140:
        return False
    rest = line[m.end() :]
    return not re.search(r"[.;]\s+\S", rest) and not re.search(r"\b(of this|see|refer|included in)\b", rest, re.I)


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def recover_item_headings(parsed: ParsedDoc, page_texts: dict[int, str]) -> int:
    """Re-insert "Item N." headings that Docling dropped.

    Docling's layout model often labels a heading at the very top of a page as page-header furniture,
    and those are discarded, so e.g. "Item 7. Management's Discussion..." vanishes and MD&A is filed
    under the previous item. The plain PyPDF text of the page still has the line; put it back as a
    heading element just before the first element that follows it on that page.
    """
    existing = {(e.page, m.group(1).lower()) for e in parsed.elements if e.kind == "heading" and (m := _ITEM_LINE.match(e.text))}
    by_page: dict[int, list[int]] = {}
    for i, e in enumerate(parsed.elements):
        by_page.setdefault(e.page, []).append(i)
    inserts: list[tuple[int, Element]] = []
    for page, text in page_texts.items():
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        items = [(i, ln) for i, ln in enumerate(lines) if _looks_like_item_heading(ln)]
        if not items or len(items) >= 4:  # none, or a table of contents
            continue
        for li, line in items:
            if (page, _ITEM_LINE.match(line).group(1).lower()) in existing or not by_page.get(page):
                continue
            before, after = _norm(" ".join(lines[:li])), _norm(" ".join(lines[li + 1 :]))
            pos = None
            for j in by_page[page]:
                probe = _norm(parsed.elements[j].text)[:30]
                if probe and probe in after and probe not in before:
                    pos = j
                    break
            if pos is not None:
                inserts.append((pos, Element(kind="heading", text=line, page=page, heading=line)))
    for pos, el in sorted(inserts, key=lambda x: x[0], reverse=True):
        parsed.elements.insert(pos, el)
    return len(inserts)


def _pypdf_pages(parsed: ParsedDoc) -> dict[int, str]:
    from ingest.manifest import local_path

    path = cache_path(parsed.meta.doc_id, "pypdf")
    if path.exists():
        pdoc = ParsedDoc.model_validate_json(path.read_text())
    else:
        src = local_path(parsed.meta)
        if not src.exists():
            return {}
        pdoc = parse_pypdf(src, parsed.meta)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pdoc.model_dump_json())
    return {e.page: e.text for e in pdoc.elements}


def assign_sections(parsed: ParsedDoc) -> ParsedDoc:
    """Post-parse pass (also applied to cached parses): recover dropped Item headings, repair split
    words, then give each element the canonical section of the headings above it."""
    if parsed.meta.doc_type in ("10-K", "10-Q", "20-F"):
        recover_item_headings(parsed, _pypdf_pages(parsed))
    section = default_section(parsed.meta.doc_type)
    for el in parsed.elements:
        if el.kind != "table":
            el.text = fix_kerning(el.text)
        el.heading = fix_kerning(el.heading)
        el.context = fix_kerning(el.context)
        if el.kind == "heading":
            section = classify_heading(el.text, section, parsed.meta.doc_type)
        el.section = section
    return parsed


def default_section(doc_type: str) -> str:
    return "Transcript" if doc_type == "earnings_call" else "Other"


# --------------------------------------------------------------------------------------------
# Docling
# --------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _docling_converter():
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(
        do_ocr=False,  # scanned PDFs are out of scope for v1
        do_table_structure=True,
        accelerator_options=AcceleratorOptions(device=AcceleratorDevice.AUTO),
    )
    opts.table_structure_options.mode = TableFormerMode.ACCURATE
    opts.table_structure_options.do_cell_matching = True
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _is_data_table(rows: list[list[str]]) -> bool:
    """Docling sometimes wraps prose or bullet layouts in tables; those are better treated as text."""
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return False
    cells = [c for r in rows for c in r if c]
    if not cells:
        return False
    numeric = sum(bool(re.search(r"\d", c)) for c in cells)
    long_prose = sum(len(c) > 200 for c in cells)
    return numeric / len(cells) > 0.15 and long_prose / len(cells) < 0.3


def _dedupe_row(row: list[str]) -> list[str]:
    """Docling repeats a spanning cell in every column it covers; collapse adjacent repeats in the label area."""
    out: list[str] = []
    for i, c in enumerate(row):
        if i > 0 and c == row[i - 1] and not re.search(r"\d", c):
            out.append("")
        else:
            out.append(c)
    return out


def parse_docling(path: Path, meta: DocMeta) -> ParsedDoc:
    from docling_core.types.doc import DocItemLabel, TableItem

    result = _docling_converter().convert(str(path))
    doc = result.document
    skip = {DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER, DocItemLabel.PICTURE, DocItemLabel.DOCUMENT_INDEX}
    section, heading = "Other", ""  # sections are assigned afterwards by assign_sections
    recent_text: list[str] = []  # short lines since the last table, used as table titles
    elements: list[Element] = []

    for item, _level in doc.iterate_items():
        label = getattr(item, "label", None)
        if label in skip or not getattr(item, "prov", None):
            continue
        page = item.prov[0].page_no
        page_end = max(p.page_no for p in item.prov)

        if isinstance(item, TableItem):
            try:
                df = item.export_to_dataframe(doc=doc)
            except Exception:  # noqa: BLE001 - malformed table, keep going
                continue
            header = [_clean(str(c)) for c in df.columns]
            rows = [header] + [_dedupe_row([_clean(str(v)) for v in r]) for r in df.astype(str).values.tolist()]
            if not _is_data_table(rows):
                text = "\n".join(" | ".join(c for c in r if c) for r in rows)
                if text.strip():
                    elements.append(
                        Element(kind="text", text=text, page=page, page_end=page_end, section=section, heading=heading)
                    )
                continue
            md = item.export_to_markdown(doc=doc)
            caption = _clean(item.caption_text(doc)) if hasattr(item, "caption_text") else ""
            context = " ".join(x for x in [caption, heading, *recent_text[-2:]] if x)[:300]
            elements.append(
                Element(
                    kind="table",
                    text=md,
                    page=page,
                    page_end=page_end,
                    section=section,
                    heading=heading,
                    rows=rows,
                    context=context,
                )
            )
            recent_text = []
            continue

        text = _clean(getattr(item, "text", "") or "")
        if not text:
            continue
        # Some filings style headings as plain bold paragraphs; catch the canonical ones anyway.
        is_item = len(text) < 120 and re.match(r"^(item\s*\d+[a-z]?\b|note\s+\d+\b)", text, re.I)
        if label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE) or is_item:
            heading = text[:200]
            elements.append(Element(kind="heading", text=text, page=page, section=section, heading=heading))
            recent_text = []
            continue
        if label == DocItemLabel.LIST_ITEM:
            text = f"- {text}"
        elements.append(Element(kind="text", text=text, page=page, section=section, heading=heading))
        if len(text) < 200:
            recent_text.append(text)
            recent_text = recent_text[-3:]

    return ParsedDoc(meta=meta, parser="docling", page_count=doc.num_pages(), elements=elements)


# --------------------------------------------------------------------------------------------
# pdfplumber fallback
# --------------------------------------------------------------------------------------------

_HEADING_LINE = re.compile(r"^(item\s*\d+[a-z]?\.?\s.{0,100}|note\s+\d+[.:]?\s.{0,100}|[A-Z][A-Z0-9 ,&'’\-]{6,90})$")


def parse_pdfplumber(path: Path, meta: DocMeta) -> ParsedDoc:
    import pdfplumber

    section, heading = "Other", ""
    elements: list[Element] = []
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            bboxes = [t.bbox for t in tables]

            def outside(obj, bboxes=bboxes):
                x0, top, x1, bottom = obj.get("x0", 0), obj.get("top", 0), obj.get("x1", 0), obj.get("bottom", 0)
                return not any(bx0 <= x0 and x1 <= bx1 and btop <= top and bottom <= bbot for bx0, btop, bx1, bbot in bboxes)

            text = page.filter(outside).extract_text() or ""
            para: list[str] = []
            for line in [*text.splitlines(), ""]:
                line = _clean(line)
                is_heading = bool(line) and len(line) < 110 and bool(_HEADING_LINE.match(line))
                long_enough = bool(line) and line.endswith((".", ":", ";")) and len(" ".join([*para, line])) > 400
                if line and not is_heading:
                    para.append(line)
                if (not line or is_heading or long_enough) and para:
                    elements.append(Element(kind="text", text=" ".join(para), page=pno, section=section, heading=heading))
                    para = []
                if is_heading:
                    heading = line
                    elements.append(Element(kind="heading", text=line, page=pno, section=section, heading=heading))

            for t in tables:
                rows = [[_clean(c or "") for c in r] for r in t.extract()]
                rows = [r for r in rows if any(r)]
                if not _is_data_table(rows):
                    continue
                md = _rows_to_markdown(rows)
                elements.append(
                    Element(kind="table", text=md, page=pno, section=section, heading=heading, rows=rows, context=heading)
                )
        n = len(pdf.pages)
    return ParsedDoc(meta=meta, parser="pdfplumber", page_count=n, elements=elements)


def _rows_to_markdown(rows: list[list[str]]) -> str:
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    esc = [[c.replace("|", "/").replace("\n", " ") for c in r] for r in rows]
    lines = ["| " + " | ".join(esc[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in esc[1:]]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# Naive baseline (ablation run A): plain page text, no structure
# --------------------------------------------------------------------------------------------


def parse_pypdf(path: Path, meta: DocMeta) -> ParsedDoc:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    elements = [
        Element(kind="text", text=(p.extract_text() or "").strip(), page=i, section="Other")
        for i, p in enumerate(reader.pages, start=1)
    ]
    return ParsedDoc(meta=meta, parser="pypdf", page_count=len(reader.pages), elements=[e for e in elements if e.text])


# --------------------------------------------------------------------------------------------
# Entry point with caching
# --------------------------------------------------------------------------------------------


def _looks_broken(parsed: ParsedDoc) -> bool:
    chars = sum(len(e.text) for e in parsed.elements)
    return parsed.page_count > 0 and chars / parsed.page_count < 150


def cache_path(doc_id: str, parser: str) -> Path:
    return get_settings().parsed_dir / parser / f"{doc_id}.json"


def parse(meta: DocMeta, path: Path, parser: str = "docling", force: bool = False) -> ParsedDoc:
    """Parse one filing.

    parser: "docling" (default, pdfplumber fallback), "pdfplumber" (fast path for uploads, seconds
    instead of minutes) or "pypdf" (naive baseline for ablation run A).
    """
    out = cache_path(meta.doc_id, "pypdf" if parser == "pypdf" else "structured")
    if out.exists() and not force:
        cached = ParsedDoc.model_validate_json(out.read_text())
        cached.meta = meta  # manifest edits (names, fiscal years) apply without re-parsing
        return cached if parser == "pypdf" else assign_sections(cached)
    if parser == "pypdf":
        parsed = parse_pypdf(path, meta)
    elif parser == "pdfplumber":
        parsed = parse_pdfplumber(path, meta)
    else:
        try:
            parsed = parse_docling(path, meta)
            if _looks_broken(parsed):
                log.warning("%s: Docling output looks too thin, using pdfplumber", meta.doc_id)
                parsed = parse_pdfplumber(path, meta)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: Docling failed (%s), using pdfplumber", meta.doc_id, e)
            parsed = parse_pdfplumber(path, meta)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(parsed.model_dump_json())
    return parsed if parser == "pypdf" else assign_sections(parsed)


def main() -> None:
    from ingest.manifest import load_documents, local_path

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", nargs="*", default=[], help="doc_ids to parse")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--parser", default="docling", choices=["docling", "pdfplumber", "pypdf"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--reverse", action="store_true", help="process in reverse order (run a second worker alongside)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    docs = load_documents()
    ids = list(docs) if args.all else args.doc
    if args.reverse:
        ids = ids[::-1]
    kind = "pypdf" if args.parser == "pypdf" else "structured"
    for doc_id in ids:
        meta = docs[doc_id]
        path = local_path(meta)
        if not path.exists():
            log.warning("%s: file missing at %s (run the download step)", doc_id, path)
            continue
        # Lock files let several workers share one queue without parsing the same filing twice.
        lock = cache_path(doc_id, kind).with_suffix(".lock")
        if not args.force and (cache_path(doc_id, kind).exists() or lock.exists()):
            continue
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
        try:
            parsed = parse(meta, path, parser=args.parser, force=args.force)
        finally:
            lock.unlink(missing_ok=True)
        n_tables = sum(e.kind == "table" for e in parsed.elements)
        log.info(
            "%s: %s pages, %s elements, %s tables (%s)", doc_id, parsed.page_count, len(parsed.elements), n_tables, parsed.parser
        )


if __name__ == "__main__":
    main()
