// Signal Lab: every signal as a card, grouped by family, with its mean rank IC, a bar for each year and the
// supporting figures; a table view holds the same numbers for comparison.
import { Building2, ChartCandlestick, FileText, LayoutGrid, Scale, ShieldCheck, Users, type LucideIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useWidth } from '../charts/util'
import { Card, Segmented } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getSignals } from '../recs/api'
import { num, pct } from '../recs/format'
import type { SignalRow, SignalStats } from '../recs/types'
import { useData } from './data'
import { Page } from './shared'

const FAMILY_ICON: Record<string, LucideIcon> = {
  Fundamentals: Building2,
  Valuation: Scale,
  'Accounting quality': ShieldCheck,
  'Filing text': FileText,
  Price: ChartCandlestick,
  'Insider activity': Users,
}
const tone = (v: number | null | undefined) => (v == null || v === 0 ? C.muted : v > 0 ? CH.pos : CH.neg)
type Sort = 'strength' | 'consistency' | 'name'

export function SignalLab() {
  const { data, error } = useData(getSignals)
  const [scope, setScope] = useState<'raw' | 'sector'>('raw')
  const [family, setFamily] = useState('')
  const [index, setIndex] = useState('')
  const [sort, setSort] = useState<Sort>('strength')
  const [view, setView] = useState<'cards' | 'table'>('cards')
  const families = useMemo(() => [...new Set((data ?? []).map((s) => s.family))].sort(), [data])
  const indexes = useMemo(() => (data?.[0]?.by_index ?? []).map((b) => b.index), [data])
  const years = useMemo(() => [...new Set((data ?? []).flatMap((s) => s.by_year.map((y) => y.year)))].sort(), [data])

  // The numbers shown: the whole universe, or the same study inside one index; across the market or within sector.
  const stats = (s: SignalRow): SignalStats | undefined => (index ? s.by_index?.find((b) => b.index === index) : s)
  const pick = (s: SignalRow) => {
    const st = stats(s)
    const raw = scope === 'raw'
    return { ic: (raw ? st?.ic_raw : st?.ic_sector) ?? null, t: (raw ? st?.t_raw : st?.t_sector) ?? null, pos: (raw ? st?.years_pos_raw : st?.years_pos_sector) ?? null, spread: (raw ? st?.spread_raw : st?.spread_sector) ?? null, coverage: st?.coverage ?? null }
  }
  const share = (pos: string | null) => {
    const [a, b] = (pos ?? '0/1').split('/').map(Number)
    return b ? a / b : 0
  }
  const rows = (data ?? [])
    .filter((s) => !family || s.family === family)
    .sort((a, b) =>
      sort === 'name' ? a.label.localeCompare(b.label) : sort === 'consistency' ? Math.abs(share(pick(b).pos) - 0.5) - Math.abs(share(pick(a).pos) - 0.5) : Math.abs(pick(b).ic ?? 0) - Math.abs(pick(a).ic ?? 0),
    )
  // One scale for every signal, whatever the filter, so a bar's length means the same thing everywhere.
  const scale = Math.max(0.01, ...(data ?? []).map((s) => Math.abs(pick(s).ic ?? 0)))
  const span = years.length ? `${years[0]}–${years[years.length - 1]}` : ''
  const groups = family || sort === 'name' ? [{ name: family || 'All signals', items: rows }] : families.map((f) => ({ name: f, items: rows.filter((s) => s.family === f) })).filter((g) => g.items.length)
  // Families in order of their strongest signal, so the most informative group comes first.
  groups.sort((a, b) => Math.max(...b.items.map((s) => Math.abs(pick(s).ic ?? 0))) - Math.max(...a.items.map((s) => Math.abs(pick(s).ic ?? 0))))

  return (
    <Page title="Signal Lab" meta={span ? <span style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>Rank IC against the next 12 months’ return · {span}</span> : undefined} error={error} loading={!data}>
      <Card style={{ padding: '12px 14px', display: 'grid', gap: 10 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
          <Segmented size="sm" value={family} onChange={setFamily} options={[{ value: '', label: 'All families' }, ...families.map((f) => ({ value: f, label: f }))]} />
          <Segmented
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: 'cards', label: 'Cards' },
              { value: 'table', label: 'Table' },
            ]}
          />
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          {indexes.length > 1 && <Segmented size="sm" value={index} onChange={setIndex} options={[{ value: '', label: 'All indexes', title: 'Every stock-month in the universe' }, ...indexes.map((i) => ({ value: i, label: i, title: `Only months a company was in the ${i}` }))]} />}
          <span aria-hidden style={{ width: 1, height: 20, background: C.rule }} />
          <Segmented
            size="sm"
            value={scope}
            onChange={setScope}
            options={[
              { value: 'raw', label: 'Across the market', title: 'Each stock ranked against the whole universe' },
              { value: 'sector', label: 'Within sector', title: 'Each stock ranked against its sector peers only' },
            ]}
          />
          <span aria-hidden style={{ width: 1, height: 20, background: C.rule }} />
          <Segmented
            size="sm"
            value={sort}
            onChange={setSort}
            options={[
              { value: 'strength', label: 'Strongest' },
              { value: 'consistency', label: 'Most consistent' },
              { value: 'name', label: 'A–Z' },
            ]}
          />
        </div>
      </Card>

      {view === 'cards' ? (
        groups.map((g) => {
          const Icon = FAMILY_ICON[g.name] ?? LayoutGrid
          return (
            <section key={g.name} style={{ display: 'grid', gap: 10 }}>
              <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.display, fontSize: 17, fontWeight: 650, color: C.text, margin: '8px 2px 0' }}>
                <span style={{ width: 28, height: 28, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: C.accentSoft, color: C.accent }}>
                  <Icon size={16} />
                </span>
                {g.name}
                <span style={{ ...NUM, fontSize: 13, fontWeight: 500, color: C.muted }}>{g.items.length}</span>
              </h2>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {g.items.map((s) => (
                  <SignalCard key={s.signal} s={s} v={pick(s)} scale={scale} scope={scope} indexNote={index ? 'Yearly bars: all indexes' : null} showFamily={groups.length === 1 && !family} />
                ))}
              </div>
            </section>
          )
        })
      ) : (
        <SignalTable rows={rows} pick={pick} scale={scale} span={index ? `${index} months` : span} />
      )}
    </Page>
  )
}

interface Picked {
  ic: number | null
  t: number | null
  pos: string | null
  spread: number | null
  coverage: number | null
}

function Meter({ v, scale, width = 120 }: { v: number | null; scale: number; width?: number | string }) {
  const half = (Math.min(Math.abs(v ?? 0), scale) / scale) * 50
  return (
    <span aria-hidden style={{ position: 'relative', width, height: 8, display: 'inline-block', borderRadius: 4, background: `color-mix(in srgb, ${C.rule} 70%, transparent)` }}>
      <span style={{ position: 'absolute', left: 'calc(50% - 0.5px)', top: -3, bottom: -3, width: 1, background: C.muted, opacity: 0.6 }} />
      <span style={{ position: 'absolute', top: 0, bottom: 0, borderRadius: 4, background: tone(v), width: `${half}%`, ...((v ?? 0) >= 0 ? { left: '50%' } : { right: '50%' }) }} />
    </span>
  )
}

function SignalCard({ s, v, scale, scope, indexNote, showFamily }: { s: SignalRow; v: Picked; scale: number; scope: 'raw' | 'sector'; indexNote: string | null; showFamily: boolean }) {
  const Icon = FAMILY_ICON[s.family] ?? LayoutGrid
  return (
    <Card style={{ padding: 16, display: 'grid', gap: 12, alignContent: 'start', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: F.body, fontSize: 14.5, fontWeight: 600, color: C.text, lineHeight: 1.35 }}>{s.label}</div>
          {showFamily && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 4, fontFamily: F.body, fontSize: 12, color: C.muted }}>
              <Icon size={12} /> {s.family}
            </div>
          )}
        </div>
        <div style={{ textAlign: 'right', flex: 'none' }}>
          <div style={{ ...NUM, fontSize: 22, fontWeight: 650, letterSpacing: '-0.01em', color: tone(v.ic) }}>{num(v.ic, 3, true)}</div>
          <div style={{ fontFamily: F.body, fontSize: 11.5, color: C.muted }}>mean rank IC</div>
        </div>
      </div>
      <Meter v={v.ic} scale={scale} width="100%" />
      <YearBars s={s} scope={scope} note={indexNote} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, borderTop: `1px solid ${C.rule}`, paddingTop: 10 }}>
        <Mini label="Years up" value={v.pos ?? '–'} />
        <Mini label="t-stat" value={num(v.t, 1, true)} />
        <Mini label="Top − bottom" value={pct(v.spread, 1, true)} />
        <Mini label="Coverage" value={pct(v.coverage, 0)} />
      </div>
    </Card>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="truncate" style={{ fontFamily: F.body, fontSize: 11, color: C.muted }}>
        {label}
      </div>
      <div style={{ ...NUM, fontSize: 13.5, fontWeight: 600, color: C.text, marginTop: 2 }}>{value}</div>
    </div>
  )
}

/** One bar per year, up green and down red, sharing a scale across cards; hovering reads out the year. */
function YearBars({ s, scope, note }: { s: SignalRow; scope: 'raw' | 'sector'; note: string | null }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const vals = s.by_year.map((y) => (scope === 'raw' ? y.ic : y.ic_sector))
  const H = 46
  const max = 0.15
  const n = vals.length
  const bw = n ? width / n : 0
  const h = hover != null ? s.by_year[hover] : null
  return (
    <div>
      <div ref={ref} style={{ height: H, position: 'relative' }} onPointerLeave={() => setHover(null)}>
        {width > 0 && (
          <svg width={width} height={H} role="img" aria-label={`${s.label}: rank IC by year`}>
            <line x1={0} x2={width} y1={H / 2} y2={H / 2} stroke="var(--color-line)" />
            {vals.map((v, i) => {
              const len = v == null ? 0 : Math.max(1.5, (Math.min(Math.abs(v), max) / max) * (H / 2 - 2))
              return (
                <g key={i} onPointerEnter={() => setHover(i)}>
                  <rect x={i * bw} y={0} width={bw} height={H} fill="transparent" />
                  {v != null && <rect x={i * bw + bw * 0.18} y={v >= 0 ? H / 2 - len : H / 2} width={bw * 0.64} height={len} rx={2} fill={v >= 0 ? CH.pos : CH.neg} opacity={hover == null || hover === i ? 1 : 0.45} />}
                </g>
              )
            })}
          </svg>
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, ...NUM, fontSize: 11, color: C.muted }}>
        {h ? (
          <span style={{ color: C.text }}>
            {h.year}: <span style={{ fontWeight: 600, color: tone(scope === 'raw' ? h.ic : h.ic_sector) }}>{num(scope === 'raw' ? h.ic : h.ic_sector, 3, true)}</span>
          </span>
        ) : (
          <>
            <span>{s.by_year[0]?.year}</span>
            {note && <span>{note}</span>}
            <span>{s.by_year[n - 1]?.year}</span>
          </>
        )}
      </div>
    </div>
  )
}

function SignalTable({ rows, pick, scale, span }: { rows: SignalRow[]; pick: (s: SignalRow) => Picked; scale: number; span: string }) {
  return (
    <Card style={{ overflow: 'hidden' }}>
      <div style={{ overflowX: 'auto' }}>
        <table className="dash-table">
          <thead>
            <tr>
              <th className="left">Signal</th>
              <th className="left" style={{ minWidth: 220 }}>
                Mean rank IC · {span}
              </th>
              <th>t-stat</th>
              <th>Years up</th>
              <th>Top − bottom</th>
              <th>Coverage</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const v = pick(s)
              const Icon = FAMILY_ICON[s.family] ?? LayoutGrid
              return (
                <tr key={s.signal}>
                  <td className="left">
                    <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ width: 28, height: 28, borderRadius: 8, flex: 'none', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: C.accentSoft, color: C.accent }} title={s.family}>
                        <Icon size={14} />
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <span style={{ display: 'block', fontFamily: F.body, fontWeight: 600, color: C.text }}>{s.label}</span>
                        <span style={{ display: 'block', fontFamily: F.body, fontSize: 12, color: C.muted }}>{s.family}</span>
                      </span>
                    </span>
                  </td>
                  <td className="left">
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
                      <Meter v={v.ic} scale={scale} width={130} />
                      <span style={{ ...NUM, fontWeight: 650, color: tone(v.ic) }}>{num(v.ic, 3, true)}</span>
                    </span>
                  </td>
                  <td>{num(v.t, 1, true)}</td>
                  <td>{v.pos ?? '–'}</td>
                  <td>{pct(v.spread, 1, true)}</td>
                  <td>{pct(v.coverage, 0)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
