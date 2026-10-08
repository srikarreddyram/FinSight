// The hosted demo: the same app, reading a static snapshot (built by scripts/build_demo.py) instead of the API.
// Every API path maps to a JSON file under demo/; compact files are expanded back to the API's shapes here, so
// the pages don't know the difference. Anything the snapshot can't answer fails with a clear message.
import { ApiError } from './api'

export const DEMO = import.meta.env.VITE_DEMO === '1'
const ROOT = `${import.meta.env.BASE_URL}demo/`

const LOCAL_ONLY = 'Available when you run FinSight locally: the hosted demo is a snapshot.'

async function file<T>(path: string): Promise<T> {
  const res = await fetch(ROOT + path)
  if (!res.ok) throw new ApiError(res.status === 404 ? 404 : res.status, LOCAL_ONLY)
  return res.json() as Promise<T>
}

/** Rows rebuilt from {months, cols: {name: values}}: the compact form the snapshot stores histories in. */
function rows(compact: { keys: string[]; cols: unknown[][] }): Record<string, unknown>[] {
  const n = compact.cols[0]?.length ?? 0
  return Array.from({ length: n }, (_, i) => Object.fromEntries(compact.keys.map((k, j) => [k, compact.cols[j][i]])))
}

let calendar: Promise<string[]> | null = null
let questions: Promise<Record<string, string>> | null = null

export async function demoRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = new URL(path, 'http://demo')
  const p = url.pathname
  const q = url.searchParams
  let m: RegExpMatchArray | null

  if (p === '/documents') return file<T>('documents.json')
  if (p === '/ingest') throw new ApiError(403, 'Uploading filings is ' + LOCAL_ONLY.charAt(0).toLowerCase() + LOCAL_ONLY.slice(1))
  if (p === '/ask') {
    const question = JSON.parse(String(init?.body ?? '{}')).question as string
    questions ??= file<Record<string, string>>('answers/index.json')
    const name = (await questions)[question.trim()]
    if (!name) throw new ApiError(404, 'The hosted demo answers the example questions only. Run FinSight locally to ask anything.')
    return file<T>(`answers/${name}`)
  }
  if ((m = p.match(/^\/recs\/(meta|watchlist|signals|backtest|risk)$/))) return file<T>(`recs/${m[1]}.json`)
  if ((m = p.match(/^\/recs\/company\/(.+)$/))) {
    const c = await file<Record<string, never>>(`recs/company/${decodeURIComponent(m[1]).toUpperCase()}.json`)
    return { ...c, signal_history: rows(c.signal_history), return_history: rows(c.return_history), risk_history: rows(c.risk_history) } as T
  }
  if (p === '/analyst') return file<T>('analyst/index.json')
  if (p === '/moves/overview') return file<T>(`moves/overview_${q.get('window') ?? '1d'}.json`)
  if ((m = p.match(/^\/analyst\/([^/]+)/))) {
    if (init?.method === 'POST') throw new ApiError(403, 'Writing a new note is ' + LOCAL_ONLY.charAt(0).toLowerCase() + LOCAL_ONLY.slice(1))
    return file<T>(`analyst/${decodeURIComponent(m[1]).toUpperCase()}.json`).catch((e) => {
      if (e instanceof ApiError && e.status === 404) return null as T // no note in the snapshot: the page offers to write one
      throw e
    })
  }
  if (p === '/moves/map') return file<T>(`moves/map_${q.get('window') ?? '1w'}.json`)
  if (p === '/moves/scan') {
    const scan = await file<Record<string, unknown>>(`moves/scan_${q.get('window') ?? '1w'}.json`)
    const limit = Number(q.get('limit') ?? 25)
    return { ...scan, falls: (scan.falls as unknown[]).slice(0, limit), gains: (scan.gains as unknown[]).slice(0, limit) } as T
  }
  if ((m = p.match(/^\/moves\/([^/]+)\/history$/))) {
    const range = q.get('range') ?? '1y'
    const days = { '1m': 21, '6m': 126, '1y': 252 }[range]
    if (!days) throw new ApiError(404, LOCAL_ONLY)
    calendar ??= file<string[]>('moves/calendar.json')
    const [cal, h] = await Promise.all([calendar, file<{ c: (number | null)[]; e: number[] }>(`moves/history/${decodeURIComponent(m[1]).toUpperCase()}.json`)])
    const offset = cal.length - h.c.length // a company listed during the year has a shorter series
    const from = Math.max(0, h.c.length - days - 1)
    const points = h.c.slice(from).map((close, i) => ({ day: cal[offset + from + i], close })).filter((pt) => pt.close != null)
    const first = points[0]?.close ?? 0
    const last = points[points.length - 1]?.close ?? 0
    return {
      ticker: m[1],
      range,
      points,
      change: first ? last / first - 1 : 0,
      earnings: h.e.map((i) => cal[offset + i]).filter((d) => d >= (points[0]?.day ?? '')),
    } as T
  }
  if ((m = p.match(/^\/moves\/([^/]+)\/earnings$/))) return file<T>(`moves/earnings/${decodeURIComponent(m[1]).toUpperCase()}.json`)
  if ((m = p.match(/^\/moves\/([^/]+)\/investigate$/))) return file<T>(`moves/${decodeURIComponent(m[1]).toUpperCase()}/analysis_${q.get('window') ?? '1w'}.json`)
  if ((m = p.match(/^\/moves\/([^/]+)$/))) return file<T>(`moves/${decodeURIComponent(m[1]).toUpperCase()}/move_${q.get('window') ?? '1w'}.json`)
  throw new ApiError(404, LOCAL_ONLY)
}

/** The page image the snapshot saved for a citation (cited pages only). */
export function demoPage(docId: string, page: number): string {
  return `${ROOT}pages/${encodeURIComponent(docId)}_p${page}.png`
}
