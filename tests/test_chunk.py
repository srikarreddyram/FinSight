from app.config import Settings
from app.schemas import DocMeta, Element, ParsedDoc
from ingest.chunk import chunk_naive, chunk_structured, n_tokens

META = DocMeta(doc_id="ACME_FY2024_10K", ticker="ACME", company="Acme", doc_type="10-K", fiscal_year=2024)


def _para(i: int, words: int = 120) -> str:
    return f"Paragraph {i}. " + " ".join(f"word{i}_{j}" for j in range(words)) + "."


def _doc() -> ParsedDoc:
    els = [Element(kind="heading", text="Item 7. MD&A", page=1, section="MD&A", heading="Item 7. MD&A")]
    els += [Element(kind="text", text=_para(i), page=1, section="MD&A", heading="Item 7. MD&A") for i in range(8)]
    els += [Element(kind="text", text=_para(10 + i), page=2, section="MD&A", heading="Results") for i in range(2)]
    rows = [["(Millions)", "2024", "2023"], ["Net sales", "32,765", "31,657"], ["Operating income", "7,207", "7,692"]]
    md = "| (Millions) | 2024 | 2023 |\n|---|---|---|\n| Net sales | 32,765 | 31,657 |\n| Operating income | 7,207 | 7,692 |"
    els.append(
        Element(
            kind="table",
            text=md,
            page=3,
            section="Financial Statements",
            heading="Income statement",
            rows=rows,
            context="Consolidated Statement of Income",
        )
    )
    return ParsedDoc(meta=META, parser="test", page_count=3, elements=els)


def test_text_chunks_respect_size_pages_and_overlap():
    s = Settings(chunk_tokens=500, chunk_overlap=0.15)
    chunks = [c for c in chunk_structured(_doc(), s) if c.chunk_type == "text"]
    assert all(c.page == c.page_end for c in chunks), "a text chunk must cite exactly one page"
    assert {c.page for c in chunks} == {1, 2}
    body = [c.text.split("\n", 1)[1] for c in chunks]
    assert all(n_tokens(b) <= 500 + 150 for b in body)
    p1 = [b for c, b in zip(chunks, body, strict=True) if c.page == 1]
    assert len(p1) >= 2
    # ~15% overlap: the next chunk opens with the tail of the previous one
    first_line = p1[1].split("\n")[0]
    assert p1[0].endswith(first_line)
    assert 20 <= n_tokens(first_line) <= 75


def test_chunks_carry_metadata_and_context_header():
    c = chunk_structured(_doc(), Settings())[0]
    assert (c.ticker, c.fiscal_year, c.fiscal_label, c.section) == ("ACME", 2024, "FY24", "MD&A")
    assert c.text.startswith("Acme (ACME) 10-K FY24 | MD&A")
    assert c.period_end == "2024-12-31"


def test_table_is_one_chunk_with_summary_and_markdown():
    tables = [c for c in chunk_structured(_doc(), Settings()) if c.chunk_type == "table"]
    assert len(tables) == 1
    t = tables[0]
    assert "Consolidated Statement of Income" in t.summary
    assert "| Net sales | 32,765 | 31,657 |" in t.text  # the LLM reads the Markdown
    assert "Net sales" in t.embed_text and "32,765" not in t.embed_text  # embedding sees summary + line items
    assert "32,765" in t.sparse_text  # BM25 can still match exact figures


def test_large_tables_split_with_repeated_header():
    rows = [["Line item", "2024", "2023"]] + [[f"Item {i}", str(i * 10), str(i * 9)] for i in range(400)]
    md = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    doc = ParsedDoc(
        meta=META,
        parser="t",
        page_count=1,
        elements=[Element(kind="table", text=md, page=5, page_end=6, rows=rows, context="Big table")],
    )
    parts = chunk_structured(doc, Settings(table_max_tokens=600))
    assert len(parts) > 1
    assert all("| Line item | 2024 | 2023 |" in p.text for p in parts)
    assert all(p.page == 5 and p.page_end == 6 for p in parts)
    assert len({p.chunk_id for p in parts}) == len(parts)


def test_naive_chunks_are_fixed_size_without_context():
    els = [Element(kind="text", text=" ".join(f"w{p}_{i}" for i in range(700)), page=p) for p in range(1, 4)]
    chunks = chunk_naive(ParsedDoc(meta=META, parser="pypdf", page_count=3, elements=els), size=1000)
    assert len(chunks) >= 2
    assert chunks[0].page == 1 and chunks[0].page_end == 2
    assert not chunks[0].text.startswith("Acme")
