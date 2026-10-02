// Mirrors app/schemas.py (the FastAPI response models).

export interface Citation {
  id: string
  label: string
  doc_id: string
  company: string
  fiscal_label: string
  page: number
  page_end: number | null
  section: string
  chunk_type: string
  snippet: string
  highlight: string
  score: number | null
}

export interface Figure {
  name: string
  value: number
  display: string
  source_id: string
  verified: boolean
}

export interface Calculation {
  name: string
  op: string
  inputs: string[]
  value: number | null
  display: string
  error: string | null
}

export interface ParsedQuery {
  question: string
  tickers: string[]
  fiscal_years: Record<string, number[]>
  sections: string[]
  doc_types: string[]
  is_comparison: boolean
  sub_queries: Record<string, string>
}

export interface Answer {
  question: string
  answer: string
  refused: boolean
  error: string | null
  citations: Citation[]
  figures: Figure[]
  calculations: Calculation[]
  table_markdown: string | null
  closest: Citation[]
  retrieved: Citation[]
  parsed_query: ParsedQuery | null
  stripped_sentences: string[]
  timings: Record<string, number>
  usage: Record<string, number>
}

export interface DocumentInfo {
  doc_id: string
  ticker: string
  company: string
  doc_type: string
  fiscal_year: number
  fiscal_label: string
  period: string
  period_end: string
  track: string
  indexed: boolean
  downloaded: boolean
}

export type Run = 'A' | 'B' | 'C' | 'D' | 'E'
