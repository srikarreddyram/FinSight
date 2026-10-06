import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Card, Segmented } from '../design/primitives'
import { C, F, GRADE_LABELS, NUM, gradeColor } from '../design/tokens'
import { getMeta, getWatchlist } from '../recs/api'
import { cap, monthLabel, pct } from '../recs/format'
import type { WatchRow } from '../recs/types'
import { go } from '../shell/routes'
import { useData } from './data'
import { BandBar, GradeChip, Page, RankMeter } from './shared'

type SortKey = 'return_rank' | 'risk_grade' | 'expected_vol' | 'severe_loss_rate' | 'market_cap' | 'ticker'
const CAPS = [
  { value: 0, label: 'Any size' },
  { value: 2e9, label: 'Over $2B' },
  { value: 1e10, label: 'Over $10B' },
  { value: 5e10, label: 'Over $50B' },
  { value: 2e11, label: 'Over $200B' },
]
const INDEX_ORDER = ['S&P 500', 'S&P 400', 'S&P 600'] // large, mid, small
const PAGE_SIZE = 50

function csv(rows: WatchRow[]): string {
  const cols: [string, (r: WatchRow) => unknown][] = [
    ['ticker', (r) => r.ticker],
    ['name', (r) => r.name],
    ['sector', (r) => r.sector],
    ['index', (r) => r.index],
    ['return_rank', (r) => r.return_rank],
    ['risk_grade', (r) => r.risk_grade],
    ['risk_label', (r) => r.risk_label],
    ['expected_volatility', (r) => r.expected_vol],
    ['severe_loss_rate', (r) => r.severe_loss_rate],
    ['market_cap', (r) => r.market_cap],
    ['top_driver', (r) => r.return_drivers[0]?.text],
  ]
  const cell = (v: unknown) => {
    const s = v == null ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  return [cols.map(([h]) => h).join(','), ...rows.map((r) => cols.map(([, f]) => cell(f(r))).join(','))].join('\n')
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  URL.revokeObjectURL(url)
}

export function Watchlist() {
  const { data: rows, error } = useData(getWatchlist)
  const { data: meta } = useData(getMeta)
  const [sector, setSector] = useState('')
  const [index, setIndex] = useState('')
  const [grades, setGrades] = useState<number[]>([])
  const [minCap, setMinCap] = useState(0)
  const [query, setQuery] = useState('')
  const [view, setView] = useState<'overall' | 'by-grade'>('overall')
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'return_rank', desc: true })
  const [page, setPage] = useState(0)

  const sectors = useMemo(() => [...new Set((rows ?? []).map((r) => r.sector).filter((s): s is string => !!s))].sort(), [rows])
  const indexes = useMemo(() => INDEX_ORDER.filter((name) => (rows ?? []).some((r) => r.index === name)), [rows])
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const out = (rows ?? []).filter(
      (r) =>
        (!sector || r.sector === sector) &&
        (!index || r.index === index) &&
        (!grades.length || (r.risk_grade != null && grades.includes(r.risk_grade))) &&
        (!minCap || (r.market_cap ?? 0) >= minCap) &&
        (!q || r.ticker.toLowerCase().includes(q) || (r.name ?? '').toLowerCase().includes(q)),
    )
    const dir = sort.desc ? -1 : 1
    const val = (r: WatchRow) => (sort.key === 'ticker' ? r.ticker : (r[sort.key] ?? -Infinity))
    out.sort((a, b) => {
      // Risk-adjusted view: grades in order, best expected return first within each grade.
      if (view === 'by-grade' && a.risk_grade !== b.risk_grade) return (a.risk_grade ?? 9) - (b.risk_grade ?? 9)
      const [x, y] = [val(a), val(b)]
      return x < y ? -dir : x > y ? dir : 0
    })
    return out
  }, [rows, sector, index, grades, minCap, query, sort, view])

  const filtered = !!(sector || index || grades.length || minCap || query)
  const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE))
  const current = Math.min(page, pages - 1)
  const slice = shown.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
  // Any change to what is shown starts again from the first page.
  const reset =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v)
      setPage(0)
    }
  const clear = () => {
    setSector('')
    setIndex('')
    setGrades([])
    setMinCap(0)
    setQuery('')
    setPage(0)
  }

  const th = (key: SortKey, label: string, title?: string, left = false) => (
    <th className={left ? 'left' : ''} aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'} title={title}>
      <button
        type="button"
        onClick={() => {
          setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'ticker' }))
          setPage(0)
        }}
      >
        {label}
        {sort.key === key && (sort.desc ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
      </button>
    </th>
  )

  return (
    <Page
      title="Watchlist"
      meta={
        meta && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <Badge tone="accent">As of {monthLabel(meta.as_of)}</Badge>
            <Badge>{meta.universe.replace(/ members$/, '')}</Badge>
          </div>
        )
      }
      aside={
        rows && (
          <button type="button" className="btn btn-secondary" onClick={() => download(`finsight-watchlist-${meta?.as_of?.slice(0, 7) ?? 'latest'}.csv`, csv(shown))}>
            <Download size={15} /> Export {filtered ? `${shown.length.toLocaleString()} rows` : 'CSV'}
          </button>
        )
      }
      error={error}
      loading={!rows}
    >
      <Card style={{ overflow: 'hidden' }}>
        {/* Toolbar */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', padding: 12, borderBottom: `1px solid ${C.rule}` }}>
          <label className="control" style={{ display: 'flex', alignItems: 'center', gap: 7, width: 'min(240px, 100%)', cursor: 'text' }}>
            <Search size={14} color={C.muted} />
            <input
              type="search"
              value={query}
              onChange={(e) => reset(setQuery)(e.target.value)}
              placeholder="Filter by ticker or name"
              aria-label="Filter by ticker or company"
              style={{ flex: 1, minWidth: 0, background: 'transparent', border: 'none', outline: 'none', font: 'inherit', color: C.text }}
            />
          </label>
          <select value={sector} onChange={(e) => reset(setSector)(e.target.value)} aria-label="Sector" className="control">
            <option value="">All sectors</option>
            {sectors.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {indexes.length > 1 && (
            <select value={index} onChange={(e) => reset(setIndex)(e.target.value)} aria-label="Index" className="control">
              <option value="">All indexes</option>
              {indexes.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          )}
          <select value={minCap} onChange={(e) => reset(setMinCap)(Number(e.target.value))} aria-label="Market cap" className="control">
            {CAPS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
          <div role="group" aria-label="Risk grade" style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
            {GRADE_LABELS.map((label, i) => {
              const g = i + 1
              const on = grades.includes(g)
              return (
                <button key={g} type="button" className="chip" aria-pressed={on} onClick={() => reset(setGrades)(on ? grades.filter((x) => x !== g) : [...grades, g])} title={`Risk grade ${g}: ${label}`}>
                  <span aria-hidden style={{ width: 8, height: 8, borderRadius: 2, background: gradeColor(g) }} />
                  {label}
                </button>
              )
            })}
          </div>
          {filtered && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={clear}>
              <X size={14} /> Clear
            </button>
          )}
          <div style={{ marginLeft: 'auto' }}>
            <Segmented
              value={view}
              onChange={reset(setView)}
              options={[
                { value: 'overall', label: 'Ranked', title: 'One ranking across the universe' },
                { value: 'by-grade', label: 'By risk grade', title: 'Grouped by risk grade, best expected return first in each' },
              ]}
            />
          </div>
        </div>

        {shown.length === 0 ? (
          <div style={{ padding: '48px 16px', textAlign: 'center' }}>
            <div style={{ fontFamily: F.body, fontSize: 14.5, fontWeight: 600, color: C.text }}>No companies match these filters</div>
            <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted, marginTop: 4 }}>Widen the size or grade filters, or clear them all.</div>
            <button type="button" className="btn btn-secondary" style={{ marginTop: 14 }} onClick={clear}>
              Clear filters
            </button>
          </div>
        ) : (
          <div style={{ overflow: 'auto', maxHeight: 'max(440px, calc(100vh - 330px))' }}>
            <table className="dash-table">
              <thead>
                <tr>
                  {th('ticker', 'Company', undefined, true)}
                  <th className="left">Sector</th>
                  {indexes.length > 1 && <th className="left">Index</th>}
                  {th('return_rank', 'Return rank')}
                  <th className="left">Expected range</th>
                  {th('risk_grade', 'Risk grade', undefined, true)}
                  {th('expected_vol', 'Volatility')}
                  {th('severe_loss_rate', 'Severe loss')}
                  {th('market_cap', 'Market cap')}
                  <th className="left">Top driver</th>
                </tr>
              </thead>
              <tbody>
                {slice.map((r) => {
                  const href = `/company/${encodeURIComponent(r.ticker)}`
                  return (
                    <tr
                      key={r.ticker}
                      className="clickable"
                      onClick={(e) => {
                        if (!(e.target as HTMLElement).closest('a')) go(href)
                      }}
                    >
                      <td className="left">
                        <a href={`#${href}`} style={{ display: 'inline-grid', color: C.text, textDecoration: 'none', minWidth: 150, maxWidth: 220 }}>
                          <span style={{ ...NUM, fontWeight: 600, color: C.accent }}>{r.ticker}</span>
                          <span className="truncate" style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>
                            {r.name}
                          </span>
                        </a>
                      </td>
                      <td className="left" style={{ fontFamily: F.body, color: C.dim, fontVariantNumeric: 'normal' }}>
                        {r.sector ?? '–'}
                      </td>
                      {indexes.length > 1 && (
                        <td className="left">
                          <Badge>{r.index ?? '–'}</Badge>
                        </td>
                      )}
                      <td>
                        <RankMeter rank={r.return_rank} />
                      </td>
                      <td className="left">
                        <BandBar band={r.band} />
                      </td>
                      <td className="left">
                        <GradeChip grade={r.risk_grade} />
                      </td>
                      <td>{pct(r.expected_vol, 0)}</td>
                      <td>{pct(r.severe_loss_rate, 0)}</td>
                      <td>{cap(r.market_cap)}</td>
                      <td className="left" style={{ fontFamily: F.body, fontSize: 12.5, color: C.dim, whiteSpace: 'normal', minWidth: 280, maxWidth: 380, fontVariantNumeric: 'normal' }}>
                        <span className="line-clamp-2">{r.return_drivers[0] ? `${r.return_drivers[0].text} (${r.return_drivers[0].effect})` : '–'}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer: count and pagination */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '10px 14px', borderTop: `1px solid ${C.rule}`, fontFamily: F.body, fontSize: 12.5, color: C.muted }}>
          <span style={NUM}>
            {shown.length === 0
              ? `0 of ${(rows?.length ?? 0).toLocaleString()} companies`
              : `${(current * PAGE_SIZE + 1).toLocaleString()}–${Math.min(shown.length, (current + 1) * PAGE_SIZE).toLocaleString()} of ${shown.length.toLocaleString()}${filtered ? ` (filtered from ${(rows?.length ?? 0).toLocaleString()})` : ''} companies`}
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
            <button type="button" className="btn btn-secondary btn-sm btn-icon" aria-label="Previous page" disabled={current === 0} onClick={() => setPage(current - 1)}>
              <ChevronLeft size={15} />
            </button>
            <span style={{ ...NUM, minWidth: 90, textAlign: 'center', color: C.dim }}>
              Page {current + 1} of {pages}
            </span>
            <button type="button" className="btn btn-secondary btn-sm btn-icon" aria-label="Next page" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
              <ChevronRight size={15} />
            </button>
          </div>
        </div>
      </Card>
    </Page>
  )
}
