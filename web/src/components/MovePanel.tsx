// "Price move" on a company page: the move split into market, sector and company-specific parts, the days that
// mattered, the dated headlines and filings, and an on-demand cited analysis of what drove it.
import { ArrowDownRight, ArrowUpRight, ExternalLink, FileText, LoaderCircle, Minus, Newspaper, RefreshCw, Sparkles } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Chip, Cited } from './Cited'
import { ApiError } from '../api'
import { Badge, Card, PanelTitle, Segmented, SectionLabel, Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getMove, investigateMove } from '../news/api'
import type { Analysis, Move, MoveEvidence, MoveWindow } from '../news/types'
import { useData } from '../pages/data'
import { money, pct } from '../recs/format'

const WINDOWS: { value: MoveWindow; label: string }[] = [
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
  { value: '1m', label: '1M' },
]

const day = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
const tone = (v: number) => (v > 0 ? CH.pos : v < 0 ? CH.neg : C.muted)

export function MovePanel({ ticker, initial = '1w' }: { ticker: string; initial?: MoveWindow }) {
  const [window, setWindow] = useState<MoveWindow>(initial)
  const { data, error } = useData(() => getMove(ticker, window), `${ticker}:${window}`)
  const [analysis, setAnalysis] = useState<Record<string, Analysis>>({})
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const key = `${ticker}:${window}`
  const result = analysis[key] ?? data?.analysis ?? null

  const run = async (refresh = false) => {
    setBusy(true)
    setFailed(null)
    try {
      const a = await investigateMove(ticker, window, refresh)
      setAnalysis((m) => ({ ...m, [key]: a }))
    } catch (e) {
      setFailed(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const evidence = data?.evidence ?? []
  const shown = showAll ? evidence : evidence.slice(0, 8)
  return (
    <Card style={{ overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', padding: '14px 18px', borderBottom: `1px solid ${C.rule}` }}>
        <PanelTitle>Price move</PanelTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {data && (
            <span style={{ ...NUM, fontSize: 12.5, color: C.muted }}>
              {day(data.move.start)} – {day(data.move.end)}
            </span>
          )}
          <Segmented size="sm" value={window} onChange={(w) => { setWindow(w); setShowAll(false); setFailed(null) }} options={WINDOWS} />
        </div>
      </div>

      {error ? (
        <div style={{ padding: '16px 18px', fontFamily: F.body, fontSize: 13, color: C.muted }}>Live prices aren’t available for this company right now ({error}).</div>
      ) : !data ? (
        <div style={{ padding: 18, display: 'grid', gap: 10 }}>
          <Skeleton w={160} h={22} />
          <Skeleton h={10} />
          <Skeleton h={10} w="80%" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <Breakdown move={data.move} evidence={evidence} />
          <div style={{ padding: '16px 18px', borderLeft: `1px solid ${C.rule}`, minWidth: 0 }}>
            <WhyItMoved ticker={ticker} move={data.move} window={window} result={result} busy={busy} failed={failed} onRun={run} evidence={evidence} />
          </div>
        </div>
      )}

      {data && evidence.length > 0 && (
        <div style={{ borderTop: `1px solid ${C.rule}` }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 18px 6px' }}>
            <SectionLabel>Headlines and filings</SectionLabel>
            <span style={{ ...NUM, fontSize: 12, color: C.muted }}>{evidence.length}</span>
          </div>
          <ul style={{ listStyle: 'none', margin: 0, padding: '0 8px 8px' }}>
            {shown.map((e) => (
              <EvidenceRow key={e.id} e={e} />
            ))}
          </ul>
          {evidence.length > shown.length && (
            <div style={{ padding: '0 18px 14px' }}>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowAll(true)}>
                Show all {evidence.length}
              </button>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

/** The total change, its three parts as bars from a shared zero line, and the days with the largest company moves. */
function Breakdown({ move, evidence }: { move: Move; evidence: MoveEvidence[] }) {
  const bigDays = move.key_days.filter((k) => Math.abs(k.change) >= 0.4).map((k) => new Date(`${k.day}T00:00:00Z`).getTime())
  const spinOff =
    bigDays.length > 0 &&
    evidence.some((e) => e.kind === 'filing' && /Acquisition or disposal completed/.test(e.title) && bigDays.some((d) => Math.abs(new Date(e.published).getTime() - d) <= 7 * 864e5))
  const parts = [
    { label: 'Market', sub: 'S&P 500', value: move.market },
    { label: 'Sector', sub: move.sector_etf ?? '–', value: move.sector },
    { label: 'Company-specific', sub: '', value: move.company },
  ]
  const scale = Math.max(0.005, ...parts.map((p) => Math.abs(p.value)))
  return (
    <div style={{ padding: '16px 18px', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ ...NUM, fontSize: 30, fontWeight: 650, letterSpacing: '-0.02em', color: tone(move.change) }}>{pct(move.change, 1, true)}</span>
        <span style={{ ...NUM, fontSize: 13, color: C.muted }}>
          {money(move.price_start)} → {money(move.price_end)}
        </span>
      </div>
      <div style={{ display: 'grid', gap: 10, marginTop: 16 }}>
        {parts.map((p) => {
          const w = (Math.abs(p.value) / scale) * 50
          return (
            <div key={p.label} style={{ display: 'grid', gridTemplateColumns: '128px 1fr 58px', alignItems: 'center', gap: 10 }}>
              <span style={{ fontFamily: F.body, fontSize: 13, color: C.dim }}>
                {p.label}
                {p.sub && <span style={{ color: C.muted }}> · {p.sub}</span>}
              </span>
              <span aria-hidden style={{ position: 'relative', height: 10 }}>
                <span style={{ position: 'absolute', left: '50%', top: -3, bottom: -3, width: 1, background: C.muted }} />
                <span
                  style={{
                    position: 'absolute',
                    top: 1,
                    height: 8,
                    left: p.value >= 0 ? '50%' : `${50 - w}%`,
                    width: `${w}%`,
                    background: tone(p.value),
                    borderRadius: p.value >= 0 ? '0 4px 4px 0' : '4px 0 0 4px',
                  }}
                />
              </span>
              <span style={{ ...NUM, fontSize: 13, fontWeight: 600, textAlign: 'right', color: C.text }}>{pct(p.value, 1, true)}</span>
            </div>
          )
        })}
      </div>
      {spinOff && (
        <div style={{ marginTop: 12 }}>
          <Badge tone="warn" title="A filing reports a completed acquisition or disposal near a very large one-day move. If shareholders received shares of a spun-off company, the fall is not a loss.">
            Possible spin-off or corporate action
          </Badge>
        </div>
      )}
      {Math.abs(move.unusual) >= 2 && !spinOff && (
        <div style={{ marginTop: 12 }}>
          <Badge tone="warn">Unusually large company-specific move</Badge>
        </div>
      )}
      {move.days > 1 && move.key_days.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <SectionLabel>Key days</SectionLabel>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto auto auto', columnGap: 18, rowGap: 6, marginTop: 8, justifyContent: 'start' }}>
            {move.key_days.map((k) => (
              <Fragment key={k.day}>
                <span style={{ ...NUM, fontSize: 13, color: C.dim }}>{day(k.day)}</span>
                <span style={{ ...NUM, fontSize: 13, fontWeight: 600, color: tone(k.change), textAlign: 'right' }}>{pct(k.change, 1, true)}</span>
                <span style={{ ...NUM, fontSize: 12.5, color: C.muted }}>company {pct(k.company, 1, true)}</span>
              </Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const PERIOD: Record<MoveWindow, string> = { '1d': 'today', '1w': 'this week', '1m': 'this month' }

function question(ticker: string, move: Move, window: MoveWindow): string {
  const dir = move.change >= 0 ? 'up' : 'down'
  return `Why is ${ticker} ${dir} ${Math.abs(move.change * 100).toFixed(1)}% ${PERIOD[window]}?`
}

/** The AI box: a question, then either a call to action or the cited answer. */
function WhyItMoved({ ticker, move, window, result, busy, failed, onRun, evidence }: { ticker: string; move: Move; window: MoveWindow; result: Analysis | null; busy: boolean; failed: string | null; onRun: (refresh?: boolean) => void; evidence: MoveEvidence[] }) {
  const head = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <span style={{ width: 36, height: 36, flex: 'none', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: C.accent, color: C.onAccent }}>
        <Sparkles size={18} strokeWidth={2.2} />
      </span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontFamily: F.body, fontSize: 16, fontWeight: 650, color: C.text, letterSpacing: '-0.01em' }}>{question(ticker, move, window)}</div>
        <div style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, marginTop: 2 }}>
          {result
            ? `AI summary of ${Math.min(result.evidence.length, 30)} sources · ${new Date(result.generated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
            : `AI summary from ${evidence.length} headlines and filings`}
        </div>
      </div>
      {result && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <Badge tone={result.confidence === 'high' ? 'verified' : result.confidence === 'medium' ? 'accent' : 'neutral'}>{result.confidence[0].toUpperCase() + result.confidence.slice(1)} confidence</Badge>
          <button type="button" className="btn btn-ghost btn-sm btn-icon" title="Run again" aria-label="Run again" onClick={() => onRun(true)}>
            <RefreshCw size={14} />
          </button>
        </div>
      )}
    </div>
  )
  const frame = { borderRadius: 14, padding: 16, border: `1px solid ${C.edge}`, background: `linear-gradient(180deg, ${C.accentSoft} 0%, ${C.surface} 70%)` }

  if (busy)
    return (
      <div style={{ ...frame, display: 'grid', gap: 12 }}>
        {head}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.body, fontSize: 13, color: C.muted }}>
          <LoaderCircle size={15} className="animate-spin" /> Reading {evidence.length} headlines and filings…
        </div>
        <Skeleton h={10} />
        <Skeleton h={10} w="88%" />
        <Skeleton h={10} w="64%" />
      </div>
    )
  if (!result)
    return (
      <div style={{ ...frame, display: 'grid', gap: 14 }}>
        {head}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn-primary" onClick={() => onRun()} disabled={evidence.length === 0}>
            <Sparkles size={15} /> Explain this move
          </button>
          {evidence.length === 0 && <span style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>No headlines or filings found for this period.</span>}
        </div>
        {failed && <span style={{ fontFamily: F.body, fontSize: 13, color: C.red }}>{failed}</span>}
      </div>
    )
  const ids = new Set(result.evidence.map((e) => e.id))
  return (
    <div style={{ ...frame, display: 'grid', gap: 14 }}>
      {head}
      <p style={{ fontFamily: F.body, fontSize: 14.5, lineHeight: 1.65, color: C.text, margin: 0 }}>
        <Cited text={result.summary} ids={ids} />
      </p>
      {result.drivers.length > 0 && (
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
          {result.drivers.map((d, i) => {
            const up = d.effect === 'pushed up'
            const down = d.effect === 'pushed down'
            const Icon = up ? ArrowUpRight : down ? ArrowDownRight : Minus
            const color = up ? CH.pos : down ? CH.neg : C.muted
            return (
              <li key={i} style={{ display: 'grid', gridTemplateColumns: '32px 1fr', gap: 12, alignItems: 'start', background: C.surface, border: `1px solid ${C.rule}`, borderRadius: 12, padding: '12px 14px' }}>
                <span style={{ width: 32, height: 32, borderRadius: 9, display: 'flex', alignItems: 'center', justifyContent: 'center', color, background: `color-mix(in srgb, ${color} 12%, transparent)` }}>
                  <Icon size={17} strokeWidth={2.4} />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: F.body, fontSize: 14, fontWeight: 600, color: C.text }}>
                    {d.headline} {!/\[[A-Z]\d/.test(d.detail) && d.evidence.map((id) => <Chip key={id} id={id} />)}
                  </div>
                  <div style={{ fontFamily: F.body, fontSize: 13.5, color: C.dim, lineHeight: 1.55, marginTop: 3 }}>
                    <Cited text={d.detail} ids={ids} />
                  </div>
                </div>
              </li>
            )
          })}
        </ol>
      )}
      <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>AI-generated from the sources below. Check them before relying on it.</div>
      {failed && <span style={{ fontFamily: F.body, fontSize: 13, color: C.red }}>{failed}</span>}
    </div>
  )
}

function EvidenceRow({ e }: { e: MoveEvidence }) {
  const Icon = e.kind === 'filing' ? FileText : Newspaper
  return (
    <li id={`ev-${e.id}`} style={{ borderRadius: 8 }}>
      <a href={e.url} target="_blank" rel="noreferrer" className="hover-lift" style={{ display: 'grid', gridTemplateColumns: '38px 58px 1fr auto', alignItems: 'center', gap: 10, padding: '7px 10px', borderRadius: 8, border: '1px solid transparent', textDecoration: 'none', color: C.text }}>
        <span style={{ ...NUM, fontSize: 11, fontWeight: 600, color: C.muted }}>{e.id}</span>
        <span style={{ ...NUM, fontSize: 12.5, color: C.muted }}>{day(e.published)}</span>
        <span style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon size={14} color={e.kind === 'filing' ? C.accent : C.muted} style={{ flex: 'none' }} />
          <span className="truncate" style={{ fontFamily: F.body, fontSize: 13.5 }}>
            {e.title}
          </span>
        </span>
        <span className="hidden sm:flex" style={{ alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 12, color: C.muted, whiteSpace: 'nowrap' }}>
          {e.source} <ExternalLink size={12} />
        </span>
      </a>
    </li>
  )
}
