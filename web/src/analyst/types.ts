// The Analyst's research note (analyst/api.py).

export interface NoteItem {
  id: string // K (10-K), X (financial fact), N (news), D (FinSight data)
  kind: 'tenk' | 'fact' | 'news' | 'data'
  title: string
  text: string // a 10-K passage, or the value of a fact or data item
  url: string | null
  meta: { item?: string; filed?: string; date?: string; source?: string; value?: boolean; fy_end?: string }
}

export interface NotePoint {
  title: string
  text: string // with [ID] citations
  evidence: string[]
}

export interface ResearchNote {
  ticker: string
  headline: string
  summary: string
  bull: NotePoint[]
  bear: NotePoint[]
  watch: NotePoint[]
  key_facts: string[] // X item IDs
  items: NoteItem[]
  generated: string
}

export interface NoteSources {
  tenk: number
  facts: number
  news: number
  data: number
  filed: string | null // the 10-K's filing date
}

/** One company's latest note, for lists. */
export interface NoteSummary {
  ticker: string
  name: string
  sector: string | null
  headline: string
  generated: string
  bull: number
  bear: number
  watch: number
}
