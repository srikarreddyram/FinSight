// Compare two companies side by side: a year of price performance from the same starting point, then risk,
// size, fundamentals from the latest annual report, insider activity and the latest research note.
import { ArrowLeftRight, FileText } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { getNote } from '../analyst/api'
import { LineChart } from '../charts/LineChart'
import { Avatar, Card, PanelTitle, Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getHistory } from '../news/api'
import { getCompany, getWatchlist } from '../recs/api'
import { cap, money, pct } from '../recs/format'
import { getFinancials, getTimeline } from '../research/api'
import { go } from '../shell/routes'
import { useData } from './data'
import { GradeChip, Page } from './shared'

const COLORS = [C.accent, 'var(--color-computed)']

function useCompany(ticker: string) {
  const company = useData(() => getCompany(ticker), ticker).data
  const history = useData(() => getHistory(ticker, '1y'), ticker).data
  const fin = useData(() => getFinancials(ticker).catch(() => null), ticker).data
  const timeline = useData(() => getTimeline(ticker).catch(() => null), ticker).data
  const note = useData(() => getNote(ticker).catch(() => null), ticker).data
  return { company, history, fin, timeline, note }
}

export function Compare({ a, b }: { a: string; b: string }) {
  const { data: list } = useData(getWatchlist, 'watchlist')
  const [since] = useState(() => new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10)) // twelve months back
  const A = useCompany(a)
  const B = useCompany(b)
  const sides = [
    { t: a, d: A },
    { t: b, d: B },
  ]

  // A year of closes, both from 100 on the first common day.
  const chart = useMemo(() => {
    const pa = A.history?.points ?? []
    const pb = new Map((B.history?.points ?? []).map((p) => [p.day, p.close]))
    const days = pa.map((p) => p.day).filter((d) => pb.has(d))
    if (days.length < 2) return null
    const ma = new Map(pa.map((p) => [p.day, p.close]))
    const a0 = ma.get(days[0])!
    const b0 = pb.get(days[0])!
    return { days, va: days.map((d) => (ma.get(d)! / a0) * 100), vb: days.map((d) => (pb.get(d)! / b0) * 100) }
  }, [A.history, B.history])

  return (
    <Page title="Compare" meta={<span style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>Two companies side by side</span>}>
      <Card style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Picker value={a} list={list} onPick={(t) => go(`/compare/${t}/${b}`)} />
        <button type="button" className="btn btn-ghost btn-icon" title="Swap" aria-label="Swap the two companies" onClick={() => go(`/compare/${b}/${a}`)}>
          <ArrowLeftRight size={16} />
        </button>
        <Picker value={b} list={list} onPick={(t) => go(`/compare/${a}/${t}`)} />
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        {sides.map(({ t, d }, i) => (
          <Card key={i} style={{ padding: 16, borderTop: `3px solid ${COLORS[i]}`, display: 'grid', gap: 10 }}>
            <a href={`#/company/${encodeURIComponent(t)}`} style={{ display: 'flex', alignItems: 'center', gap: 12, textDecoration: 'none', color: C.text }}>
              <Avatar ticker={t} name={d.company?.card.name} size={44} />
              <span style={{ minWidth: 0 }}>
                <span className="truncate" style={{ display: 'block', fontFamily: F.display, fontSize: 18, fontWeight: 650 }}>
                  {d.company?.card.name ?? t}
                </span>
                <span style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted }}>
                  {t} · {d.company?.card.index} · {d.company?.card.sector}
                </span>
              </span>
            </a>
            {d.history ? (
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span style={{ ...NUM, fontSize: 26, fontWeight: 650, color: C.text }}>{money(d.history.points.at(-1)?.close)}</span>
                <span style={{ ...NUM, fontSize: 14, fontWeight: 600, color: d.history.change >= 0 ? CH.pos : CH.neg }}>{pct(d.history.change, 1, true)} in a year</span>
              </div>
            ) : (
              <Skeleton h={30} w="60%" />
            )}
            {d.note && (
              <a href={`#/company/${encodeURIComponent(t)}?tab=note`} style={{ display: 'flex', gap: 8, padding: '8px 10px', borderRadius: 10, background: C.accentSoft, textDecoration: 'none', color: C.text, fontFamily: F.body, fontSize: 13, lineHeight: 1.45 }}>
                <FileText size={14} color={C.accent} style={{ flex: 'none', marginTop: 2 }} /> {d.note.headline}
              </a>
            )}
          </Card>
        ))}
      </div>

      <Card style={{ padding: '14px 18px' }}>
        <PanelTitle>Past year, from the same start</PanelTitle>
        <div style={{ marginTop: 8 }}>
          {chart ? (
            <LineChart
              x={chart.days}
              height={260}
              format={(v) => `${v.toFixed(1)}`}
              axisFormat={(v) => `${Math.round(v)}`}
              series={[
                { name: a, color: COLORS[0], values: chart.va },
                { name: b, color: COLORS[1], values: chart.vb },
              ]}
            />
          ) : (
            <Skeleton h={260} r={10} />
          )}
        </div>
      </Card>

      <Card style={{ padding: '6px 0' }}>
        <Section title="Risk" />
        <Row label="Risk grade" a={<GradeChip grade={A.company?.card.risk_grade ?? null} />} b={<GradeChip grade={B.company?.card.risk_grade ?? null} />} />
        <Row label="Expected volatility" a={pct(A.company?.card.expected_vol, 0)} b={pct(B.company?.card.expected_vol, 0)} bars={[A.company?.card.expected_vol, B.company?.card.expected_vol]} />
        <Row label="Fell 40%+ within a year, similar stocks" a={pct(A.company?.card.severe_loss_rate, 0)} b={pct(B.company?.card.severe_loss_rate, 0)} bars={[A.company?.card.severe_loss_rate, B.company?.card.severe_loss_rate]} />
        <Row label="Volatility, past year" a={pct(A.company?.card.vol_12m, 0)} b={pct(B.company?.card.vol_12m, 0)} bars={[A.company?.card.vol_12m, B.company?.card.vol_12m]} />
        <Section title="Size and fundamentals" />
        <Row label="Market cap" a={cap(A.company?.card.market_cap)} b={cap(B.company?.card.market_cap)} bars={[A.company?.card.market_cap, B.company?.card.market_cap]} />
        {(['revenue', 'net_income', 'cash', 'long_term_debt'] as const).map((item) => {
          const va = A.fin?.rows.find((r) => r.item === item)?.values[0]?.value
          const vb = B.fin?.rows.find((r) => r.item === item)?.values[0]?.value
          const label = A.fin?.rows.find((r) => r.item === item)?.label ?? B.fin?.rows.find((r) => r.item === item)?.label ?? item
          return <Row key={item} label={`${label}, latest year`} a={va == null ? '–' : cap(va)} b={vb == null ? '–' : cap(vb)} bars={[va, vb]} />
        })}
        {['Gross margin', 'Net margin'].map((label) => {
          const va = A.fin?.ratios.find((r) => r.label === label)?.values[0]
          const vb = B.fin?.ratios.find((r) => r.label === label)?.values[0]
          return <Row key={label} label={label} a={pct(va, 1)} b={pct(vb, 1)} bars={[va, vb]} />
        })}
        <Section title="Insiders, past year" />
        <Row label="Insider purchases" a={String(insiders(A.timeline?.events, 'buy', since))} b={String(insiders(B.timeline?.events, 'buy', since))} />
        <Row label="Insider sales" a={String(insiders(A.timeline?.events, 'sell', since))} b={String(insiders(B.timeline?.events, 'sell', since))} />
      </Card>
    </Page>
  )
}

/** Insider trades of one side over the past twelve months, counted the same way as the timeline. */
function insiders(events: { date: string; insider?: { side: string } }[] | undefined, side: 'buy' | 'sell', since: string): number | string {
  if (!events) return '–'
  return events.filter((e) => e.insider?.side === side && e.date >= since).length
}

function Section({ title }: { title: string }) {
  return <div style={{ padding: '14px 18px 4px', fontFamily: F.body, fontSize: 12, fontWeight: 650, letterSpacing: '0.04em', textTransform: 'uppercase', color: C.muted }}>{title}</div>
}

/** One measure: the left company's value, the label with a two-sided bar between, the right company's value. */
function Row({ label, a, b, bars }: { label: string; a: ReactNode; b: ReactNode; bars?: (number | null | undefined)[] }) {
  const [x, y] = (bars ?? []).map((v) => (v == null ? 0 : Math.abs(v)))
  const max = Math.max(x ?? 0, y ?? 0) || 1
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(140px, 1.2fr) minmax(0, 1fr)', gap: 12, alignItems: 'center', padding: '9px 18px', borderTop: `1px solid ${C.rule}` }}>
      <span style={{ ...NUM, fontSize: 14, fontWeight: 600, color: C.text, display: 'flex', justifyContent: 'flex-end' }}>{a}</span>
      <span style={{ display: 'grid', gap: 5, textAlign: 'center' }}>
        <span style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted }}>{label}</span>
        {bars && (
          <span aria-hidden style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, height: 6 }}>
            <span style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <span style={{ width: `${((x ?? 0) / max) * 100}%`, background: COLORS[0], borderRadius: '3px 0 0 3px' }} />
            </span>
            <span>
              <span style={{ display: 'block', height: '100%', width: `${((y ?? 0) / max) * 100}%`, background: COLORS[1], borderRadius: '0 3px 3px 0' }} />
            </span>
          </span>
        )}
      </span>
      <span style={{ ...NUM, fontSize: 14, fontWeight: 600, color: C.text }}>{b}</span>
    </div>
  )
}

function Picker({ value, list, onPick }: { value: string; list: { ticker: string; name: string | null }[] | null; onPick: (t: string) => void }) {
  const [text, setText] = useState('')
  const id = `pick-${value}`
  return (
    <span style={{ flex: '1 1 240px', minWidth: 0 }}>
      <input
        className="control"
        list={id}
        value={text}
        placeholder={`${value} — type a ticker or name to change`}
        aria-label="Company to compare"
        onChange={(e) => {
          setText(e.target.value)
          const t = e.target.value.split(' ')[0].toUpperCase()
          if (list?.some((r) => r.ticker === t)) {
            onPick(t)
            setText('')
          }
        }}
        style={{ width: '100%' }}
      />
      <datalist id={id}>
        {(list ?? []).map((r) => (
          <option key={r.ticker} value={`${r.ticker} — ${r.name ?? ''}`} />
        ))}
      </datalist>
    </span>
  )
}
