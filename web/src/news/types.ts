// Shapes served by /moves/* (news/api.py).
export type MoveWindow = '1d' | '1w' | '1m'
export type PriceRange = '1m' | '6m' | '1y' | '5y'

export interface EarningsEvent {
  date: string
  change: number
  market: number
  vs_market: number
}

export interface EarningsReaction {
  ticker: string
  events: EarningsEvent[]
  summary: {
    count: number
    typical?: number
    up?: number
    largest_up?: EarningsEvent
    largest_down?: EarningsEvent
    last?: EarningsEvent
    last_rank?: number | null
    last_biggest_since?: string | null
  }
}

export interface MapTile {
  ticker: string
  name: string | null
  sector: string
  index: string | null
  cap: number
  change: number
  price: number
  vs_sector: number | null
}

export interface MarketMapData {
  status: 'ready' | 'building' | 'error'
  as_of?: string
  window?: MoveWindow
  tiles?: MapTile[]
}

export interface PriceHistory {
  ticker: string
  range: PriceRange
  points: { day: string; close: number }[]
  change: number
  earnings: string[]
}

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

/** A company on the home page: its move over the window. */
export interface HomeMover {
  ticker: string
  name: string | null
  sector: string | null
  price: number
  change: number
  vs_sector: number | null
}

export interface IndexSummary {
  name: string // 'S&P 500'
  symbol: string // '^GSPC'
  level: number | null
  change: number | null
  spark: [string, number][] // a month of closes
  up: number // members up over the window
  down: number
  gainers: HomeMover[]
  losers: HomeMover[]
}

export interface SectorMove {
  name: string
  etf: string
  change: number
}

export interface Explained extends HomeMover {
  analysis: Analysis | null
}

export interface Overview {
  status: 'ready' | 'building' | 'error'
  error?: string | null
  as_of?: string
  window?: MoveWindow
  indexes?: IndexSummary[]
  sectors?: SectorMove[]
  explained?: Explained[]
}
