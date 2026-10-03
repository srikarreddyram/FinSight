// Shapes served by /recs/* (recs/api.py). Missing values arrive as null.
export interface Driver {
  signal: string
  label: string
  scope: 'market' | 'sector'
  value: string | null
  effect: string
  text: string
}

export interface Band {
  p25: number
  p50: number
  p75: number
  n: number
}

export interface WatchRow {
  ticker: string
  name: string | null
  sector: string | null
  index?: string | null
  market_cap: number | null
  return_rank: number
  return_decile: number
  rank_in_grade: number | null
  band: Band | null
  return_drivers: Driver[]
  risk_grade: number | null
  risk_label: string | null
  previous_grade: number | null
  expected_vol: number | null
  severe_loss_rate: number | null
  risk_pillar: string | null
  risk_pillar_effect?: string | null
  risk_drivers: Driver[]
  vol_12m: number | null
  beta: number | null
}

export interface Meta {
  as_of: string
  built: string
  companies: number
  universe: string
  indexes?: Record<string, number>
  returns_model: { trained_through: string; rows: number; features: number; labels: string; validation_ic: number | null }
  risk_models: Record<string, { trained_through: string; rows: number; features: string; target: string; validation: number | null }>
  return_bands: Record<string, Band>
  risk_components: { vol: Record<string, number>; severe: Record<string, number> }
  holdout_note: string
}

export interface SignalStats {
  coverage: number | null
  ic_raw: number | null
  t_raw: number | null
  years_pos_raw: string | null
  spread_raw: number | null
  ic_sector: number | null
  t_sector: number | null
  years_pos_sector: string | null
  spread_sector: number | null
}

export interface SignalRow extends SignalStats {
  signal: string
  label: string
  family: string
  by_index?: (SignalStats & { index: string })[]
  by_year: { year: number; ic: number | null; ic_sector: number | null }[]
}

export interface BacktestStats {
  ann_return: number
  ann_vol: number
  sharpe: number | null
  max_drawdown: number
  months: number
  avg_turnover: number
}

export interface BacktestMonth {
  month: string
  long: number
  short: number
  long_short: number
  long_short_net: number
  bench: number
  turnover: number
}

export interface BacktestModel {
  stats: Record<'long' | 'short' | 'bench' | 'long_short' | 'long_short_net', BacktestStats>
  monthly: BacktestMonth[]
  by_year: { year: number; long_short: number; long_short_net: number; bench: number; ic: number }[]
  mean_ic: number
}

export interface BacktestIndex {
  index: string
  from: string
  months: number
  companies: number
  mean_ic: Record<string, number>
  stats: BacktestModel['stats']
}

export interface Backtest {
  q: number
  cost_bps: number
  models: Record<string, BacktestModel>
  by_index?: BacktestIndex[]
  checks?: {
    ic: { universe: string; model: string; kind: 'raw' | 'neutral'; ic: number; t: number | null; years: number }[]
    exposures: Record<string, Record<string, number>>
    unscored: Record<string, number>
  } | null
}

export interface RiskSummary {
  overall: Record<string, number | null>
  by_year: Record<string, number | null>[]
  calibration: { grade: string; n: number; realised_vol: number; severe_rate: number }[]
  by_sector: { sector: string; n: number; severe_rate: number; auc_final: number | null; auc_trailing_vol: number | null }[]
  grade_change_rate: number
  smoothing_months: number
  stability: { smoothing_months: number; grade_change_rate: number; severe_rate_low: number; severe_rate_severe: number; vol_low: number; vol_severe: number }[]
  by_index?: {
    index: string
    n: number
    severe_rate: number
    median_fwd_vol: number
    vol_ic_final: number
    vol_ic_trailing: number
    monthly_auc_final: number
    monthly_auc_trailing_vol: number
    share_graded_severe: number
  }[]
  distribution: { sector: string; risk_grade: number; n: number }[]
  pillars: Record<string, number>
}

export interface CompanyPayload {
  card: WatchRow
  signals: { signal: string; label: string; family: string; format: string }[]
  signal_history: Record<string, number | string | null>[]
  return_history: { month: string; return_rank: number | null; excess_ret: number | null }[]
  risk_history: { month: string; grade: number | null; fwd_vol: number | null; severe: number | null; vol_12m: number | null }[]
}
