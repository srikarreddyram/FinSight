import { useMemo, useState } from 'react'
import { Card, Segmented } from '../design/primitives'
import { C, F, GRADE_LABELS, NUM, gradeColor } from '../design/tokens'
import { getMeta, getWatchlist } from '../recs/api'
import { cap, monthLabel, pct } from '../recs/format'
import type { WatchRow } from '../recs/types'
import { link, useData } from './data'
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
const control = {
  fontFamily: F.mono,
  fontSize: 11,
  padding: '7px 10px',
  borderRadius: 6,
  background: C.surface,
  color: C.text,
  border: `1px solid ${C.rule}`,
} as const

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

  const th = (key: SortKey, label: string, title?: string, left = false) => (
    <th className={left ? 'left' : ''} aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'} title={title}>
      <button type="button" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'ticker' }))}>
        {label}
        {sort.key === key ? (sort.desc ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )

  return (
    <Page
      title="Watchlist"
      lead={
        <>
          Every current {meta?.universe ? meta.universe.replace(/ members$/, '') : 'index'} member ranked on the return model’s expected 12-month return relative to the S&amp;P 500, next to its risk grade. In testing, stocks at the top of this ranking did not reliably beat those at the bottom, so treat a rank as a prompt to read the filing, not as a forecast.
          {meta && ` As of ${monthLabel(meta.as_of)}; the model last trained on outcomes through ${monthLabel(meta.returns_model.trained_through)}.`}
        </>
      }
      error={error}
      loading={!rows}
    >
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ticker or company" aria-label="Search by ticker or company" style={{ ...control, width: 190 }} />
        <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector" style={control}>
          <option value="">All sectors</option>
          {sectors.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        {indexes.length > 1 && (
          <select value={index} onChange={(e) => setIndex(e.target.value)} aria-label="Index" style={control}>
            <option value="">All indexes</option>
            {indexes.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        )}
        <select value={minCap} onChange={(e) => setMinCap(Number(e.target.value))} aria-label="Market cap" style={control}>
          {CAPS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <div role="group" aria-label="Risk grade" style={{ display: 'inline-flex', gap: 4 }}>
          {GRADE_LABELS.map((label, i) => {
            const g = i + 1
            const on = grades.includes(g)
            return (
              <button
                key={g}
                type="button"
                aria-pressed={on}
                onClick={() => setGrades((cur) => (on ? cur.filter((x) => x !== g) : [...cur, g]))}
                style={{ ...control, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6, borderColor: on ? C.accent : C.rule, background: on ? C.hover : C.surface }}
              >
                <span aria-hidden style={{ width: 9, height: 9, borderRadius: 2, background: gradeColor(g) }} />
                {label}
              </button>
            )
          })}
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: 'overall', label: 'Overall', title: 'One ranking across the universe' },
              { value: 'by-grade', label: 'Within risk grade', title: 'Grouped by risk grade, best expected return first in each' },
            ]}
          />
        </div>
      </div>

      <Card style={{ overflow: 'hidden' }}>
        <div style={{ ...NUM, fontSize: 10.5, color: C.muted, letterSpacing: '0.08em', padding: '10px 14px', borderBottom: `1px solid ${C.rule}` }}>
          {shown.length} OF {rows?.length ?? 0} COMPANIES
        </div>
        <div style={{ overflow: 'auto', maxHeight: '70vh' }}>
          <table className="dash-table">
            <thead>
              <tr>
                {th('ticker', 'Company', undefined, true)}
                <th className="left">Sector</th>
                {indexes.length > 1 && <th className="left">Index</th>}
                {th('return_rank', 'Return rank', 'Percentile of the model’s expected 12-month return relative to the S&P 500 (100 = highest)')}
                <th className="left" title="12-month return minus the S&P 500 earned by stocks in the same predicted decile, 2015–2024: median, with the middle half as a bar">
                  Past outcomes
                </th>
                {th('risk_grade', 'Risk grade', '1 Low to 5 Severe: expected volatility and severe-loss rate, ranked within the month')}
                {th('expected_vol', 'Volatility', 'Realised 12-month volatility of stocks in the same predicted decile, 2015–2024')}
                {th('severe_loss_rate', 'Severe loss', 'Share of stocks in the same predicted decile that fell 40% or more within 12 months, 2015–2024')}
                {th('market_cap', 'Market cap')}
                <th className="left">Biggest driver of the rank</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.ticker}>
                  <td className="left">
                    <a href={link(`/company/${r.ticker}`)} style={{ color: C.text, textDecoration: 'none', display: 'inline-grid' }}>
                      <span style={{ fontWeight: 600, color: C.accent }}>{r.ticker}</span>
                      <span style={{ fontFamily: F.body, fontSize: 11.5, color: C.muted, maxWidth: 190, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name}</span>
                    </a>
                  </td>
                  <td className="left" style={{ fontFamily: F.body, color: C.dim }}>
                    {r.sector ?? '–'}
                  </td>
                  {indexes.length > 1 && (
                    <td className="left" style={{ color: C.dim }}>
                      {r.index ?? '–'}
                    </td>
                  )}
                  <td>
                    <RankMeter rank={r.return_rank} />
                  </td>
                  <td className="left">
                    <BandBar band={r.band} />
                  </td>
                  <td>
                    <GradeChip grade={r.risk_grade} />
                  </td>
                  <td>{pct(r.expected_vol, 0)}</td>
                  <td>{pct(r.severe_loss_rate, 0)}</td>
                  <td>{cap(r.market_cap)}</td>
                  <td className="left" style={{ fontFamily: F.body, color: C.dim, whiteSpace: 'normal', minWidth: 260, maxWidth: 380 }}>
                    {r.return_drivers[0] ? `${r.return_drivers[0].text} (${r.return_drivers[0].effect})` : '–'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </Page>
  )
}
