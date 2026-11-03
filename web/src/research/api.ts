import { request } from '../api'
import type { AsOf, Financials, RiskChanges, TimelineEvent } from './types'

const t = (ticker: string) => encodeURIComponent(ticker)
export const getChanges = (ticker: string) => request<RiskChanges>(`/research/${t(ticker)}/changes`)
export const getTimeline = (ticker: string) => request<{ ticker: string; events: TimelineEvent[] }>(`/research/${t(ticker)}/timeline`)
export const getFinancials = (ticker: string) => request<Financials>(`/research/${t(ticker)}/financials`)
export const getAsOfMonths = () => request<string[]>('/research/asof/months')
export const getAsOf = (month: string) => request<AsOf>(`/research/asof?month=${month}`)
