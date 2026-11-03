// Company research (research/api.py): 10-K changes, the event timeline, sourced financials, the time machine.

export type Segment = ['=' | '+' | '-', string]

export interface ChangeBlock {
  status: 'same' | 'changed' | 'new' | 'removed'
  heading: boolean
  text?: string
  segments?: Segment[]
}

export interface FilingRef {
  accn: string
  filed: string
  url: string
  words: number
}

export interface RiskChanges {
  ticker: string
  current: FilingRef
  previous: FilingRef
  summary: { same: number; changed: number; new: number; removed: number }
  blocks: ChangeBlock[]
  removed: ChangeBlock[]
}

export interface TimelineEvent {
  date: string
  kind: 'earnings' | 'report' | 'leadership' | 'deal' | 'event' | 'late' | 'insider'
  title: string
  form: string
  url: string
  reaction?: { change: number; vs_market: number } | null
  insider?: { name: string; role: string; side: 'buy' | 'sell'; shares: number; price: number | null; value: number | null }
}

export interface SourcedValue {
  value: number
  form: string | null
  accn: string | null
  filed: string
  url: string | null
}

export interface Financials {
  ticker: string
  years: string[]
  rows: { item: string; label: string; values: (SourcedValue | null)[] }[]
  ratios: { label: string; values: (number | null)[]; formula: string }[]
}

export interface AsOfRow {
  ticker: string
  name: string
  listed: boolean
  sector: string | null
  tier: string | null
  rank: number | null
  grade: number | null
  next_12m: number | null
  severe: boolean | null
}

export interface AsOf {
  month: string
  rows: AsOfRow[]
  by_grade: { grade: number; n: number; next_12m: number | null; severe: number | null }[]
}
