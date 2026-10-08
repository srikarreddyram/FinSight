import { request } from '../api'
import type { NoteSources, NoteSummary, ResearchNote } from './types'

/** The latest note on the company, or null if none has been written. */
export const getNote = (ticker: string) => request<ResearchNote | null>(`/analyst/${encodeURIComponent(ticker)}`)
export const writeNote = (ticker: string, refresh = false) =>
  request<ResearchNote>(`/analyst/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`, { method: 'POST' })
/** Step one of writing a note: the sources it will be written from, counted. */
export const gatherSources = (ticker: string) => request<NoteSources>(`/analyst/${encodeURIComponent(ticker)}/context`, { method: 'POST' })
/** The latest note on each company that has one, newest first. */
export const listNotes = (limit = 8) => request<NoteSummary[]>(`/analyst?limit=${limit}`)
