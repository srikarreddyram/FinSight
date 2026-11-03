// "Timeline" on a company page: three years of the company's own disclosures on one track — earnings (with the
// stock's two-session reaction), annual and quarterly reports, leadership changes, deals and insider trades —
// each linking to the filing on EDGAR.
import { AlertTriangle, ArrowDownRight, ArrowUpRight, BarChart3, Bell, ExternalLink, FileText, Handshake, UserCog, type LucideIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Card, Segmented, Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { useData } from '../pages/data'
import { pct } from '../recs/format'
import { getTimeline } from '../research/api'
import type { TimelineEvent } from '../research/types'

type Filter = 'all' | 'earnings' | 'report' | 'leadership' | 'deal' | 'insider'
const KIND: Record<TimelineEvent['kind'], { icon: LucideIcon; color: string; group: Filter }> = {
  earnings: { icon: BarChart3, color: C.accent, group: 'earnings' },
  report: { icon: FileText, color: 'var(--color-computed)', group: 'report' },
  leadership: { icon: UserCog, color: 'var(--grade-3)', group: 'leadership' },
  deal: { icon: Handshake, color: 'var(--grade-2)', group: 'deal' },
  event: { icon: Bell, color: C.muted, group: 'all' },
  late: { icon: AlertTriangle, color: CH.neg, group: 'report' },
  insider: { icon: ArrowUpRight, color: CH.pos, group: 'insider' },
}
const monthOf = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const dayOf = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
const usd = (v: number | null | undefined) => (v == null ? '–' : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${Math.round(v)}`)

export function Timeline({ ticker }: { ticker: string }) {
  const { data, error } = useData(() => getTimeline(ticker), ticker)
  const [filter, setFilter] = useState<Filter>('all')
  const events = useMemo(() => data?.events ?? [], [data])
  const [since] = useState(() => new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10)) // twelve months back
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const e of events) c[KIND[e.kind].group] = (c[KIND[e.kind].group] ?? 0) + 1
    return c
  }, [events])
  const year = useMemo(() => {
    const ins = events.filter((e) => e.insider && e.date >= since)
    const side = (s: 'buy' | 'sell') => ins.filter((e) => e.insider!.side === s)
    const total = (es: TimelineEvent[]) => es.reduce((a, e) => a + (e.insider!.value ?? 0), 0)
    return { buys: side('buy').length, sells: side('sell').length, bought: total(side('buy')), sold: total(side('sell')), people: new Set(ins.map((e) => e.insider!.name)).size }
  }, [events, since])

  if (error) return <Card style={{ padding: 18, fontFamily: F.body, fontSize: 13.5, color: C.muted }}>{error}</Card>
  if (!data) return <Skeleton h={320} r={14} />
  const shown = events.filter((e) => filter === 'all' || KIND[e.kind].group === filter)
  const byMonth: [string, TimelineEvent[]][] = []
  for (const e of shown) {
    const m = monthOf(e.date)
    if (byMonth.length && byMonth[byMonth.length - 1][0] === m) byMonth[byMonth.length - 1][1].push(e)
    else byMonth.push([m, [e]])
  }
  const label = (f: Filter, l: string) => ({ value: f, label: f === 'all' ? `${l} ${events.length}` : `${l} ${counts[f] ?? 0}` })

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Mini label="Insider buys, 12 months" value={String(year.buys)} note={usd(year.bought)} color={year.buys ? CH.pos : C.text} />
        <Mini label="Insider sales, 12 months" value={String(year.sells)} note={usd(year.sold)} color={year.sells ? CH.neg : C.text} />
        <Mini label="Insiders trading" value={String(year.people)} note="directors and officers" />
        <Mini label="Earnings reports" value={String(counts.earnings ?? 0)} note="in three years" />
      </div>
      <Card style={{ padding: '14px 18px 18px' }}>
        <Segmented size="sm" value={filter} onChange={setFilter} options={[label('all', 'All'), label('earnings', 'Earnings'), label('report', 'Reports'), label('leadership', 'Leadership'), label('deal', 'Deals'), label('insider', 'Insiders')]} />
        {byMonth.length === 0 ? (
          <p style={{ fontFamily: F.body, fontSize: 13.5, color: C.muted, margin: '18px 0 0' }}>Nothing of this kind in the past three years.</p>
        ) : (
          byMonth.map(([month, list]) => (
            <section key={month} style={{ marginTop: 16 }}>
              <h3 style={{ fontFamily: F.body, fontSize: 12, fontWeight: 650, letterSpacing: '0.04em', textTransform: 'uppercase', color: C.muted, margin: '0 0 6px' }}>{month}</h3>
              <ol style={{ listStyle: 'none', margin: 0, padding: 0, position: 'relative' }}>
                <span aria-hidden style={{ position: 'absolute', left: 17, top: 8, bottom: 8, width: 2, background: C.rule, borderRadius: 1 }} />
                {list.map((e, i) => (
                  <Row key={`${e.url}-${i}`} e={e} />
                ))}
              </ol>
            </section>
          ))
        )}
      </Card>
    </div>
  )
}

function Mini({ label, value, note, color = C.text }: { label: string; value: string; note: string; color?: string }) {
  return (
    <Card style={{ padding: '12px 14px' }}>
      <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>{label}</div>
      <div style={{ ...NUM, fontSize: 22, fontWeight: 650, color, marginTop: 2 }}>{value}</div>
      <div style={{ ...NUM, fontSize: 12, color: C.muted }}>{note}</div>
    </Card>
  )
}

function Row({ e }: { e: TimelineEvent }) {
  const k = KIND[e.kind]
  const sell = e.insider?.side === 'sell'
  const Icon = e.insider ? (sell ? ArrowDownRight : ArrowUpRight) : k.icon
  const color = e.insider ? (sell ? CH.neg : CH.pos) : k.color
  return (
    <li style={{ position: 'relative' }}>
      <a href={e.url} target="_blank" rel="noreferrer" className="hover-lift" style={{ display: 'grid', gridTemplateColumns: '36px minmax(0, 1fr) auto', gap: 12, alignItems: 'center', padding: '7px 8px 7px 0', borderRadius: 10, border: '1px solid transparent', textDecoration: 'none', color: C.text }}>
        <span style={{ position: 'relative', zIndex: 1, width: 36, height: 36, borderRadius: 11, display: 'flex', alignItems: 'center', justifyContent: 'center', color, background: `color-mix(in srgb, ${color} 13%, var(--color-card))`, border: `1px solid color-mix(in srgb, ${color} 30%, transparent)` }}>
          <Icon size={16} />
        </span>
        <span style={{ minWidth: 0 }}>
          <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 14, fontWeight: 600 }}>
            {e.insider ? `${e.insider.name} ${sell ? 'sold' : 'bought'} ${usd(e.insider.value)}` : e.title}
          </span>
          <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 12.5, color: C.muted, marginTop: 1 }}>
            {e.insider
              ? `${e.insider.role} · ${Math.round(e.insider.shares).toLocaleString()} shares${e.insider.price ? ` at $${e.insider.price.toFixed(2)}` : ''}`
              : e.kind === 'earnings' && e.reaction
                ? `Stock ${pct(e.reaction.change, 1, true)} over two sessions · ${pct(e.reaction.vs_market, 1, true)} vs S&P 500`
                : `Form ${e.form}`}
          </span>
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {e.kind === 'earnings' && e.reaction && <span style={{ ...NUM, fontSize: 13, fontWeight: 650, color: e.reaction.vs_market >= 0 ? CH.pos : CH.neg }}>{pct(e.reaction.vs_market, 1, true)}</span>}
          <span style={{ ...NUM, fontSize: 12.5, color: C.muted, whiteSpace: 'nowrap' }}>{dayOf(e.date)}</span>
          <ExternalLink size={13} color={C.muted} />
        </span>
      </a>
    </li>
  )
}
