import { request } from '../api'
import type { Analysis, CompanyMove, MoveWindow, Scan } from './types'

export const getMove = (ticker: string, window: MoveWindow) => request<CompanyMove>(`/moves/${encodeURIComponent(ticker)}?window=${window}`)
export const investigateMove = (ticker: string, window: MoveWindow, refresh = false) =>
  request<Analysis>(`/moves/${encodeURIComponent(ticker)}/investigate?window=${window}${refresh ? '&refresh=true' : ''}`, { method: 'POST' })
export const getScan = (window: MoveWindow, limit = 25) => request<Scan>(`/moves/scan?window=${window}&limit=${limit}`)
