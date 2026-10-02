import type { Answer, Citation, DocumentInfo, Run } from './types'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, init)
  } catch (e) {
    if (init?.signal?.aborted) throw e // a newer question replaced this one: not a connection problem
    throw new ApiError(0, 'Cannot reach the FinSight API. Start it with `uv run uvicorn app.api:app`.')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export function ask(question: string, run: Run, signal?: AbortSignal): Promise<Answer> {
  return request<Answer>('/ask', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question, run }),
    signal,
  })
}

export function listDocuments(): Promise<DocumentInfo[]> {
  return request<DocumentInfo[]>('/documents')
}

export interface IngestReport {
  doc_id: string
  status: string
  chunks: number
  tables?: number
  total_s?: number
}

export function ingest(form: FormData): Promise<IngestReport> {
  return request<IngestReport>('/ingest', { method: 'POST', body: form })
}

/** Rendered page PNG with the passages the answer used highlighted. */
export function pageImageUrl(c: Pick<Citation, 'doc_id' | 'page' | 'highlight' | 'snippet' | 'chunk_type'>, page = c.page) {
  const params = new URLSearchParams({
    snippet: (c.highlight || c.snippet || '').slice(0, 1500),
    rows: String(c.chunk_type === 'table'),
  })
  return `${BASE}/documents/${encodeURIComponent(c.doc_id)}/page/${page}.png?${params}`
}

export function pdfUrl(docId: string, page: number) {
  return `${BASE}/documents/${encodeURIComponent(docId)}/pdf#page=${page}`
}
