import { request } from '../api'
import type { Backtest, CompanyPayload, Meta, RiskSummary, SignalRow, WatchRow } from './types'

export const getMeta = () => request<Meta>('/recs/meta')
export const getWatchlist = () => request<WatchRow[]>('/recs/watchlist')
export const getSignals = () => request<SignalRow[]>('/recs/signals')
export const getBacktest = () => request<Backtest>('/recs/backtest')
export const getRisk = () => request<RiskSummary>('/recs/risk')
export const getCompany = (ticker: string) => request<CompanyPayload>(`/recs/company/${encodeURIComponent(ticker)}`)
