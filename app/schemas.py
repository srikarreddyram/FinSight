"""Data models shared by ingestion, retrieval, answering, the API and eval."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app import fiscal

DocType = Literal["10-K", "10-Q", "20-F", "8-K", "annual_report", "earnings_call", "other"]
ChunkType = Literal["text", "table"]


class Company(BaseModel):
    ticker: str
    name: str
    country: str = "US"
    fiscal_year_end_month: int = 12  # 3 for most Indian companies (April-March years)
    aliases: list[str] = Field(default_factory=list)


class DocMeta(BaseModel):
    doc_id: str
    ticker: str
    company: str
    doc_type: DocType
    fiscal_year: int  # the calendar year in which the fiscal year ends (FY26 = Apr 2025-Mar 2026 -> 2026)
    period: str = "FY"  # FY, Q1..Q4
    fiscal_year_end_month: int = 12
    url: str | None = None
    local_path: str | None = None
    track: str = "custom"

    @property
    def fiscal_label(self) -> str:
        return fiscal.label(self.fiscal_year, self.period)

    @property
    def period_start(self) -> date:
        return fiscal.period_bounds(self.fiscal_year, self.period, self.fiscal_year_end_month)[0]

    @property
    def period_end(self) -> date:
        return fiscal.period_bounds(self.fiscal_year, self.period, self.fiscal_year_end_month)[1]


class Element(BaseModel):
    """One parsed unit of a filing, in reading order."""

    kind: Literal["text", "heading", "table"]
    text: str  # plain text; for tables, the Markdown rendering
    page: int  # 1-indexed
    page_end: int | None = None
    section: str = "Other"  # canonical section, e.g. "MD&A", "Risk Factors"
    heading: str = ""  # nearest raw heading above this element
    rows: list[list[str]] | None = None  # tables only: header row first
    context: str = ""  # tables only: title/caption text found just above the table


class ParsedDoc(BaseModel):
    meta: DocMeta
    parser: str
    page_count: int
    elements: list[Element]


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    ticker: str
    company: str
    doc_type: str
    fiscal_year: int
    fiscal_label: str
    period: str
    period_end: str  # ISO date: the calendar end of the reporting period
    section: str
    heading: str
    page: int
    page_end: int
    chunk_type: ChunkType
    text: str  # what the LLM reads
    embed_text: str  # what gets embedded (dense)
    sparse_text: str  # what gets BM25-indexed
    summary: str = ""  # tables: one-line description

    @property
    def cite_label(self) -> str:
        return f"{self.company} {self.fiscal_label} p.{self.page}"


class Hit(BaseModel):
    chunk: Chunk
    rrf_score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rerank_score: float | None = None  # sigmoid of the cross-encoder logit


class ParsedQuery(BaseModel):
    question: str
    tickers: list[str] = Field(default_factory=list)
    fiscal_years: dict[str, list[int]] = Field(default_factory=dict)  # per ticker, after resolving "last year"
    sections: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    is_comparison: bool = False
    sub_queries: dict[str, str] = Field(default_factory=dict)  # ticker -> rewritten single-company query


class Citation(BaseModel):
    id: str  # S1, S2, ...
    label: str  # "Infosys FY25 p.112"
    doc_id: str
    company: str
    fiscal_label: str
    page: int
    page_end: int | None = None
    section: str
    chunk_type: str
    snippet: str
    highlight: str = ""  # quotes of the figures the answer took from this source, for the viewer
    score: float | None = None


class Figure(BaseModel):
    name: str
    value: float
    display: str
    source_id: str
    verified: bool


class Calculation(BaseModel):
    name: str
    op: str
    inputs: list[str]
    value: float | None
    display: str
    error: str | None = None


class Answer(BaseModel):
    question: str
    answer: str
    refused: bool = False
    error: str | None = None  # the model couldn't be reached or failed; distinct from "not found"
    citations: list[Citation] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    calculations: list[Calculation] = Field(default_factory=list)
    table_markdown: str | None = None
    closest: list[Citation] = Field(default_factory=list)  # shown when refusing
    retrieved: list[Citation] = Field(default_factory=list)  # reranked evidence list, for eval/debug
    parsed_query: ParsedQuery | None = None
    stripped_sentences: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    usage: dict[str, int] = Field(default_factory=dict)
