// Shapes served by /moves/* (news/api.py).
export type MoveWindow = '1d' | '1w' | '1m'

export interface MoveEvidence {
  id: string
  kind: 'news' | 'filing'
  title: string
  source: string
  url: string
  published: string
}

export interface KeyDay {
  day: string
  change: number
  company: number
}

export interface Move {
  ticker: string
  days: number
  start: string
  end: string
  price_start: number
  price_end: number
  change: number
  market: number
  sector: number
  company: number
  beta_market: number
  beta_sector: number | null
  sector_etf: string | null
  r2: number
  unusual: number
  key_days: KeyDay[]
}

export interface Driver {
  headline: string
  detail: string
  effect: 'pushed up' | 'pushed down' | 'mixed'
  evidence: string[]
}

export interface Analysis {
  summary: string
  drivers: Driver[]
  confidence: 'low' | 'medium' | 'high'
  evidence: MoveEvidence[]
  generated: string
}

export interface CompanyMove {
  company: { ticker: string; name: string | null; sector: string | null; index: string | null }
  window: MoveWindow
  move: Move
  evidence: MoveEvidence[]
  analysis: Analysis | null
}

export interface MoverRow {
  ticker: string
  price: number | null
  name: string | null
  index: string | null
  sector: string | null
  risk_grade: number | null
  change: number
  vs_market: number
  vs_sector: number | null
  excess: number
  max_day: number | null
}

export interface Scan {
  status: 'ready' | 'building' | 'error'
  error?: string | null
  started?: string | null
  as_of?: string
  built?: string
  window?: MoveWindow
  market?: number
  breadth?: { up: number; down: number }
  falls?: MoverRow[]
  gains?: MoverRow[]
}
