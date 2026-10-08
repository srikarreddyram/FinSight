// The home page under the Copilot's ask box: the three indexes, today's top movers and sectors, why the S&P 500's
// biggest movers moved, the latest research notes and this month's risk grade changes.
import { ArrowRight, FileText, LoaderCircle, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { listNotes } from '../analyst/api'
import { ApiError } from '../api'
import { Sparkline } from '../charts/Sparkline'
import { Avatar, Card, PanelTitle, Segmented, Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getOverview, investigateMove } from '../news/api'
import type { Analysis, Explained, HomeMover, IndexSummary, Overview, SectorMove } from '../news/types'
import { getWatchlist } from '../recs/api'
import { money, pct } from '../recs/format'
import type { WatchRow } from '../recs/types'
import { useData } from './data'
import { GradeChip } from './shared'

const tone = (v: number | null | undefined) => (v == null || v === 0 ? C.muted : v > 0 ? CH.pos : CH.neg)
const level = (v: number | null) => (v == null ? '–' : v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const day = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
const plain = (text: string) => text.replace(/\s*\[[A-Z]\d+(?:\s*,\s*[A-Z]\d+)*\]/g, '')
const clamp = (lines: number) => ({ display: '-webkit-box', WebkitLineClamp: lines, WebkitBoxOrient: 'vertical' as const, overflow: 'hidden' })

function SectionHead({ title, note, action }: { title: string; note?: string; action?: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, margin: '10px 2px 2px' }}>
      <h2 style={{ fontFamily: F.display, fontSize: 19, fontWeight: 650, letterSpacing: '-0.01em', color: C.text, margin: 0 }}>
        {title}
        {note && <span style={{ fontFamily: F.body, fontSize: 13, fontWeight: 500, color: C.muted, marginLeft: 10 }}>{note}</span>}
      </h2>
      {action}
    </div>
  )
}

function More({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: F.body, fontSize: 13.5, fontWeight: 600, color: C.accent, textDecoration: 'none', whiteSpace: 'nowrap' }}>
      {children} <ArrowRight size={14} />
    </a>
  )
}

export function HomeDashboard() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)

  // The day's first scan takes a couple of minutes; poll until it is ready.
  useEffect(() => {
    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = () =>
      getOverview('1d')
        .then((o) => {
          if (!live) return
          setData(o)
          setError(o.status === 'error' ? (o.error ?? 'Prices are unavailable right now') : null)
          if (o.status === 'building') timer = setTimeout(load, 4000)
        })
        .catch((e) => live && setError(e instanceof ApiError ? e.message : String(e)))
    load()
    return () => {
      live = false
      if (timer) clearTimeout(timer)
    }
  }, [])

  const ready = data?.status === 'ready'
  return (
    <div style={{ maxWidth: 1240, margin: '28px auto 0', display: 'grid', gap: 16 }}>
      <SectionHead title="Markets today" note={ready && data.as_of ? `Prices to ${day(data.as_of)}` : undefined} action={<More href="#/movers">All movers</More>} />
      {error && !ready ? (
        <Card style={{ padding: '18px 20px', fontFamily: F.body, fontSize: 13.5, color: C.muted }}>Market data isn’t available right now ({error}).</Card>
      ) : !ready ? (
        <>
          {data?.status === 'building' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.body, fontSize: 13, color: C.muted }}>
              <LoaderCircle size={14} className="animate-spin" color={C.accent} /> Fetching today’s prices
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} h={168} r={12} />
            ))}
          </div>
          <Skeleton h={340} r={12} />
        </>
      ) : (
        <>
          <div className="-mx-4 flex snap-x scroll-px-4 gap-3 overflow-x-auto px-4 pb-1 md:mx-0 md:grid md:grid-cols-3 md:overflow-visible md:px-0 md:pb-0">
            {(data.indexes ?? []).map((x) => (
              <IndexCard key={x.symbol} x={x} />
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
            <TopMovers indexes={data.indexes ?? []} />
            <Sectors sectors={data.sectors ?? []} />
          </div>
          {(data.explained ?? []).length > 0 && (
            <>
              <SectionHead title="Why they moved" note="S&P 500 · today" />
              <WhyTheyMoved items={data.explained ?? []} />
            </>
          )}
        </>
      )}
      <LatestNotes />
      <RiskChanges />
    </div>
  )
}

function IndexCard({ x }: { x: IndexSummary }) {
  const [hover, setHover] = useState<number | null>(null)
  const closes = x.spark.map((p) => p[1])
  const month = closes.length > 1 ? closes[closes.length - 1] / closes[0] - 1 : 0
  const h = hover != null ? x.spark[hover] : null
  return (
    <Card className="w-[78vw] max-w-[320px] flex-none snap-start md:w-auto md:max-w-none" style={{ padding: '14px 16px 12px', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontFamily: F.body, fontSize: 14, fontWeight: 600, color: C.text }}>{x.name}</span>
        <span style={{ ...NUM, fontSize: 12, color: C.muted }}>{h ? `${day(h[0])} · ${level(h[1])}` : `1M ${pct(month, 1, true)}`}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 4, flexWrap: 'wrap' }}>
        <span style={{ ...NUM, fontSize: 25, fontWeight: 650, letterSpacing: '-0.015em', color: C.text }}>{level(x.level)}</span>
        <span style={{ ...NUM, fontSize: 14, fontWeight: 600, color: tone(x.change) }}>{pct(x.change, 2, true)}</span>
      </div>
      <div style={{ marginTop: 8 }}>
        <Sparkline points={closes} color={month >= 0 ? CH.pos : CH.neg} onHover={setHover} />
      </div>
      <Breadth up={x.up} down={x.down} />
    </Card>
  )
}

function Breadth({ up, down }: { up: number; down: number }) {
  const total = up + down || 1
  return (
    <div style={{ marginTop: 10 }} aria-label={`${up} members up, ${down} down`}>
      <div style={{ display: 'flex', gap: 2, height: 6, borderRadius: 3, overflow: 'hidden' }}>
        <span style={{ width: `${(up / total) * 100}%`, background: CH.pos }} />
        <span style={{ flex: 1, background: CH.neg }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontFamily: F.body, fontSize: 12, color: C.muted }}>
        <span>
          <span style={{ ...NUM, fontWeight: 600, color: C.dim }}>{up}</span> up
        </span>
        <span>
          <span style={{ ...NUM, fontWeight: 600, color: C.dim }}>{down}</span> down
        </span>
      </div>
    </div>
  )
}

function TopMovers({ indexes }: { indexes: IndexSummary[] }) {
  const [side, setSide] = useState<'gainers' | 'losers'>('gainers')
  const [index, setIndex] = useState(indexes[0]?.name ?? 'S&P 500')
  const rows = indexes.find((i) => i.name === index)?.[side] ?? []
  return (
    <Card style={{ padding: '14px 16px 14px', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <Segmented
          value={side}
          onChange={setSide}
          options={[
            { value: 'gainers', label: 'Top gainers' },
            { value: 'losers', label: 'Top losers' },
          ]}
        />
        <Segmented size="sm" value={index} onChange={setIndex} options={indexes.map((i) => ({ value: i.name, label: i.name }))} />
      </div>
      {rows.length === 0 ? (
        <div style={{ fontFamily: F.body, fontSize: 13.5, color: C.muted, padding: '24px 4px' }}>No {side} today.</div>
      ) : (
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {rows.map((r) => (
            <MoverCard key={r.ticker} r={r} />
          ))}
        </div>
      )}
      <div style={{ marginTop: 'auto', paddingTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
        <More href="#/movers">All movers</More>
      </div>
    </Card>
  )
}

function MoverCard({ r }: { r: HomeMover }) {
  return (
    <a href={`#/company/${encodeURIComponent(r.ticker)}`} className="hover-lift" style={{ display: 'grid', gap: 8, padding: 12, borderRadius: 12, border: `1px solid ${C.rule}`, textDecoration: 'none', color: C.text, minWidth: 0 }}>
      <Avatar ticker={r.ticker} name={r.name} size={34} />
      <span className="truncate" style={{ fontFamily: F.body, fontSize: 13.5, fontWeight: 600 }} title={r.name ?? r.ticker}>
        {r.name ?? r.ticker}
      </span>
      <span>
        <span style={{ ...NUM, display: 'block', fontSize: 15, fontWeight: 600 }}>{money(r.price)}</span>
        <span style={{ ...NUM, display: 'block', fontSize: 13, fontWeight: 600, color: tone(r.change), marginTop: 2 }}>{pct(r.change, 2, true)}</span>
      </span>
    </a>
  )
}

function Sectors({ sectors }: { sectors: SectorMove[] }) {
  const max = Math.max(0.005, ...sectors.map((s) => Math.abs(s.change)))
  return (
    <Card style={{ padding: '14px 16px 12px', minWidth: 0 }}>
      <PanelTitle style={{ marginBottom: 8 }}>Sectors</PanelTitle>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid' }}>
        {sectors.map((s) => (
          <li key={s.etf} style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 92px 58px', alignItems: 'center', gap: 10, padding: '6px 0', borderTop: `1px solid ${C.rule}` }}>
            <span className="truncate" style={{ fontFamily: F.body, fontSize: 13.5, color: C.text }} title={`${s.name} (${s.etf})`}>
              {s.name}
            </span>
            <span aria-hidden style={{ position: 'relative', height: 8 }}>
              <span style={{ position: 'absolute', left: 'calc(50% - 0.5px)', top: -3, bottom: -3, width: 1, background: C.muted, opacity: 0.45 }} />
              <span
                style={{
                  position: 'absolute',
                  top: 0,
                  bottom: 0,
                  borderRadius: 2,
                  background: s.change >= 0 ? CH.pos : CH.neg,
                  width: `max(3px, ${(Math.abs(s.change) / max) * 50}%)`,
                  ...(s.change >= 0 ? { left: '50%' } : { right: '50%' }),
                }}
              />
            </span>
            <span style={{ ...NUM, fontSize: 13, fontWeight: 600, textAlign: 'right', color: tone(s.change) }}>{pct(s.change, 2, true)}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function WhyTheyMoved({ items }: { items: Explained[] }) {
  const [written, setWritten] = useState<Record<string, Analysis | 'failed'>>({})
  // Explanations not written yet are written one at a time, so the free tier's per-minute limit isn't hit.
  useEffect(() => {
    let live = true
    void (async () => {
      for (const e of items) {
        if (!live) return
        if (e.analysis) continue
        try {
          const a = await investigateMove(e.ticker, '1d')
          if (live) setWritten((w) => ({ ...w, [e.ticker]: a }))
        } catch {
          if (live) setWritten((w) => ({ ...w, [e.ticker]: 'failed' }))
        }
      }
    })()
    return () => {
      live = false
    }
  }, [items])

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((e) => {
        const a = e.analysis ?? written[e.ticker] ?? null
        const href = `#/company/${encodeURIComponent(e.ticker)}?w=1d`
        return (
          <Card key={e.ticker} style={{ padding: 16, minWidth: 0, display: 'grid', gap: 12, alignContent: 'start' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '36px minmax(0, 1fr) auto', gap: 10, alignItems: 'center' }}>
              <Avatar ticker={e.ticker} name={e.name} size={36} />
              <span style={{ minWidth: 0 }}>
                <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 14, fontWeight: 600, color: C.text }}>
                  {e.name ?? e.ticker}
                </span>
                <span style={{ ...NUM, display: 'block', fontSize: 12, color: C.muted, marginTop: 1 }}>
                  {e.ticker} · {pct(e.vs_sector, 1, true)} vs sector
                </span>
              </span>
              <span style={{ ...NUM, fontSize: 13, fontWeight: 650, color: tone(e.change), background: `color-mix(in srgb, ${tone(e.change)} 12%, transparent)`, borderRadius: 999, padding: '3px 9px' }}>{pct(e.change, 1, true)}</span>
            </div>
            {a === null ? (
              <div style={{ display: 'grid', gap: 8 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 12.5, color: C.muted }}>
                  <Sparkles size={13} color={C.accent} /> Reading the news…
                </span>
                <Skeleton h={9} />
                <Skeleton h={9} w="90%" />
                <Skeleton h={9} w="70%" />
              </div>
            ) : a === 'failed' ? (
              <p style={{ fontFamily: F.body, fontSize: 13.5, lineHeight: 1.55, color: C.muted, margin: 0 }}>No explanation yet; the company page has the full breakdown.</p>
            ) : (
              <p style={{ fontFamily: F.body, fontSize: 13.5, lineHeight: 1.55, color: C.dim, margin: 0, ...clamp(5) }}>{plain(a.summary)}</p>
            )}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, borderTop: `1px solid ${C.rule}`, paddingTop: 10 }}>
              <span style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>{a && a !== 'failed' ? `${a.evidence.length} sources` : ' '}</span>
              <More href={href}>Read more</More>
            </div>
          </Card>
        )
      })}
    </div>
  )
}

function LatestNotes() {
  const { data } = useData(() => listNotes(4), 'notes')
  if (!data || data.length === 0) return null
  return (
    <>
      <SectionHead title="Research notes" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data.map((n) => (
          <a key={n.ticker} href={`#/company/${encodeURIComponent(n.ticker)}?tab=note`} className="hover-lift" style={{ display: 'grid', gap: 10, alignContent: 'start', padding: 16, borderRadius: 12, border: `1px solid ${C.rule}`, background: C.surface, textDecoration: 'none', color: C.text, minWidth: 0 }}>
            <span style={{ display: 'grid', gridTemplateColumns: '32px minmax(0, 1fr)', gap: 10, alignItems: 'center' }}>
              <Avatar ticker={n.ticker} name={n.name} size={32} />
              <span style={{ minWidth: 0 }}>
                <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 13.5, fontWeight: 600 }}>
                  {n.name}
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 1 }}>
                  <FileText size={12} /> {day(n.generated)}
                </span>
              </span>
            </span>
            <span style={{ fontFamily: F.body, fontSize: 14.5, fontWeight: 600, lineHeight: 1.4, letterSpacing: '-0.005em', ...clamp(3) }}>{n.headline}</span>
            <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <Tag color={CH.pos}>{n.bull} bull</Tag>
              <Tag color={CH.neg}>{n.bear} bear</Tag>
              <Tag color={C.accent}>{n.watch} to watch</Tag>
            </span>
          </a>
        ))}
      </div>
    </>
  )
}

function Tag({ color, children }: { color: string; children: ReactNode }) {
  return <span style={{ ...NUM, fontSize: 11.5, fontWeight: 600, color, background: `color-mix(in srgb, ${color} 11%, transparent)`, borderRadius: 999, padding: '2px 8px' }}>{children}</span>
}

function RiskChanges() {
  const { data } = useData(getWatchlist, 'watchlist')
  const { raised, lowered } = useMemo(() => {
    const changed = (data ?? []).filter((r) => r.risk_grade != null && r.previous_grade != null && r.risk_grade !== r.previous_grade)
    const big = (rows: WatchRow[]) => rows.sort((a, b) => (b.market_cap ?? 0) - (a.market_cap ?? 0))
    return { raised: big(changed.filter((r) => r.risk_grade! > r.previous_grade!)), lowered: big(changed.filter((r) => r.risk_grade! < r.previous_grade!)) }
  }, [data])
  if (!data || raised.length + lowered.length === 0) return null
  const column = (title: string, rows: WatchRow[]) => (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontFamily: F.body, fontSize: 12.5, fontWeight: 600, letterSpacing: '0.03em', textTransform: 'uppercase', color: C.muted, margin: '0 0 4px' }}>
        {title} <span style={{ ...NUM, color: C.dim }}>{rows.length}</span>
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {rows.slice(0, 5).map((r) => (
          <li key={r.ticker}>
            <a href={`#/company/${encodeURIComponent(r.ticker)}`} className="hover-lift" style={{ display: 'grid', gridTemplateColumns: '30px minmax(0, 1fr) auto', gap: 10, alignItems: 'center', padding: '8px 6px', borderRadius: 8, border: '1px solid transparent', textDecoration: 'none', color: C.text }}>
              <Avatar ticker={r.ticker} name={r.name} size={30} />
              <span className="truncate" style={{ fontFamily: F.body, fontSize: 13.5, fontWeight: 600 }}>
                {r.name ?? r.ticker}
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <GradeChip grade={r.previous_grade} compact />
                <ArrowRight size={13} color={C.muted} />
                <GradeChip grade={r.risk_grade} />
              </span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
  return (
    <>
      <SectionHead title="Risk grade changes" note="this month" action={<More href="#/risk">Risk</More>} />
      <Card style={{ padding: '14px 16px' }}>
        <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
          {column('Raised', raised)}
          {column('Lowered', lowered)}
        </div>
      </Card>
    </>
  )
}
