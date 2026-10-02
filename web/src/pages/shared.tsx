// Pieces every dashboard page uses: the page frame with its standing disclaimer, grade and band marks.
import type { ReactNode } from 'react'
import { Card, ErrorState } from '../design/primitives'
import { C, F, GRADE_LABELS, NUM, gradeColor } from '../design/tokens'
import { pct } from '../recs/format'
import type { Band } from '../recs/types'

export function Page({ title, lead, aside, error, loading, children }: { title: string; lead: ReactNode; aside?: ReactNode; error?: string | null; loading?: boolean; children?: ReactNode }) {
  return (
    <main style={{ maxWidth: 1400, margin: '0 auto', padding: '26px 20px 48px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap', marginBottom: 18 }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontFamily: F.display, fontWeight: 700, fontSize: 40, lineHeight: 1, letterSpacing: '0.02em', textTransform: 'uppercase', margin: 0, textWrap: 'balance' }}>{title}</h1>
          <p style={{ fontFamily: F.body, fontSize: 14, color: C.muted, margin: '10px 0 0', maxWidth: 760, lineHeight: 1.6 }}>{lead}</p>
        </div>
        {aside}
      </div>
      {error ? (
        <ErrorState title="The dashboard data didn’t load" message={error} hint="start the API with `uv run uvicorn app.api:app`, and build the data with `uv run python -m recs.build`" />
      ) : loading ? (
        <Card style={{ padding: 28, fontFamily: F.mono, fontSize: 11, letterSpacing: '0.18em', color: C.muted, textTransform: 'uppercase' }}>Loading…</Card>
      ) : (
        <div className="anim-fade-up" style={{ display: 'grid', gap: 16 }}>
          {children}
        </div>
      )}
      <p style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 26, lineHeight: 1.6, maxWidth: 860 }}>
        FinSight is a research and education tool. Its ranks and grades describe statistical patterns in public filings and prices; they are not personal financial advice and not a recommendation to buy or sell anything.
      </p>
    </main>
  )
}

/** A risk grade: the ramp colour as a swatch, the grade's number and name always in text beside it. */
export function GradeChip({ grade, compact = false }: { grade: number | null; compact?: boolean }) {
  if (grade == null) return <span style={{ color: C.muted }}>–</span>
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap' }}>
      <span aria-hidden style={{ width: 10, height: 10, borderRadius: 2, background: gradeColor(grade), flex: 'none' }} />
      <span style={{ ...NUM, fontSize: 12, color: C.text }}>{grade}</span>
      {!compact && <span style={{ fontFamily: F.body, fontSize: 12, color: C.dim }}>{GRADE_LABELS[grade - 1]}</span>}
    </span>
  )
}

/** Return rank as a number with a thin meter under it. */
export function RankMeter({ rank }: { rank: number }) {
  return (
    <span style={{ display: 'inline-grid', gap: 3, justifyItems: 'end', minWidth: 54 }}>
      <span style={{ ...NUM, fontSize: 12.5, fontWeight: 600, color: C.text }}>{rank.toFixed(0)}</span>
      <span aria-hidden style={{ width: 54, height: 3, background: C.rule, borderRadius: 2, overflow: 'hidden' }}>
        <span style={{ display: 'block', width: `${rank}%`, height: '100%', background: C.accent }} />
      </span>
    </span>
  )
}

/** What stocks in the same predicted decile went on to return: middle half as a bar, median as a tick, zero as a hairline. */
export function BandBar({ band, lo = -0.3, hi = 0.3 }: { band: Band | null; lo?: number; hi?: number }) {
  if (!band) return <span style={{ color: C.muted }}>–</span>
  const x = (v: number) => `${((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100}%`
  return (
    <span
      title={`Middle half of outcomes: ${pct(band.p25, 0, true)} to ${pct(band.p75, 0, true)}; median ${pct(band.p50, 1, true)} (12-month return minus the S&P 500, ${band.n.toLocaleString()} past cases)`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
    >
      <span aria-hidden style={{ position: 'relative', width: 92, height: 10, display: 'inline-block' }}>
        <span style={{ position: 'absolute', left: x(0), top: 0, bottom: 0, width: 1, background: C.muted }} />
        <span style={{ position: 'absolute', left: x(band.p25), width: `calc(${x(band.p75)} - ${x(band.p25)})`, top: 3, height: 4, background: C.dim, opacity: 0.45, borderRadius: 2 }} />
        <span style={{ position: 'absolute', left: x(band.p50), top: 0, bottom: 0, width: 2, background: C.text, borderRadius: 1 }} />
      </span>
      <span style={{ ...NUM, fontSize: 11.5, color: C.dim }}>{pct(band.p50, 1, true)}</span>
    </span>
  )
}

export function StatRow({ children }: { children: ReactNode }) {
  return (
    <Card style={{ padding: '18px 20px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 20 }}>{children}</div>
    </Card>
  )
}
