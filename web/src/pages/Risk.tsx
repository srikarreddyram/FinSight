// Risk: the five grades as a ladder (how many companies hold each now, and how often stocks graded that way fell
// 40% or more within a year), the month's grade changes, what drives the grades, and how they spread across
// indexes and sectors.
import { Activity, ArrowDown, ArrowRight, ArrowUp, Calculator, FileText, Landmark, ShieldAlert, Zap, type LucideIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ChartCard } from '../charts/core'
import { StackedBars } from '../charts/StackedBars'
import { Avatar, Card, PanelTitle } from '../design/primitives'
import { C, F, GRADE_LABELS, NUM, gradeColor } from '../design/tokens'
import { getRisk, getWatchlist } from '../recs/api'
import { pct } from '../recs/format'
import type { WatchRow } from '../recs/types'
import { useData } from './data'
import { GradeChip, Page } from './shared'

const PILLAR_ICON: Record<string, LucideIcon> = {
  'Market risk': Activity,
  'Disclosure risk': FileText,
  'Financial health': Landmark,
  'Earnings quality': Calculator,
  'Event risk': Zap,
}

export function Risk() {
  const { data, error } = useData(getRisk)
  const { data: watch } = useData(getWatchlist)
  const sectors = useMemo(() => {
    const by = new Map<string, number[]>()
    for (const d of data?.distribution ?? []) {
      const row = by.get(d.sector) ?? [0, 0, 0, 0, 0]
      row[d.risk_grade - 1] = d.n
      by.set(d.sector, row)
    }
    return [...by.entries()].map(([label, counts]) => ({ label, counts })).sort((a, b) => a.label.localeCompare(b.label))
  }, [data])
  const counts = useMemo(() => [1, 2, 3, 4, 5].map((g) => (watch ?? []).filter((r) => r.risk_grade === g).length), [watch])
  const changed = useMemo(() => (watch ?? []).filter((r) => r.risk_grade != null && r.previous_grade != null && r.risk_grade !== r.previous_grade).sort((a, b) => (b.market_cap ?? 0) - (a.market_cap ?? 0)), [watch])
  const raised = changed.filter((r) => r.risk_grade! > r.previous_grade!)
  const lowered = changed.filter((r) => r.risk_grade! < r.previous_grade!)
  const pillars = Object.entries(data?.pillars ?? {}).sort((a, b) => b[1] - a[1])
  const pillarTotal = pillars.reduce((a, [, n]) => a + n, 0) || 1
  const maxSevere = Math.max(...(data?.calibration ?? []).map((c) => c.severe_rate), 0.01)

  return (
    <Page title="Risk" meta={<span style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>Grades 1 Low to 5 Severe, refreshed monthly</span>} error={error} loading={!data}>
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            {data.calibration.map((c, i) => {
              const g = i + 1
              const color = gradeColor(g)
              return (
                <Card key={c.grade} style={{ padding: 0, overflow: 'hidden', display: 'grid' }}>
                  <div style={{ height: 5, background: color }} />
                  <div style={{ padding: '14px 16px 16px', display: 'grid', gap: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ ...NUM, width: 26, height: 26, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: C.text, background: `color-mix(in srgb, ${color} 38%, var(--color-card))`, border: `1px solid ${color}` }}>{g}</span>
                        <span style={{ fontFamily: F.body, fontSize: 14.5, fontWeight: 650, color: C.text }}>{GRADE_LABELS[i]}</span>
                      </span>
                      <span style={{ ...NUM, fontSize: 12.5, color: C.muted }}>{watch ? `${counts[i].toLocaleString()} now` : ''}</span>
                    </div>
                    <div>
                      <div style={{ ...NUM, fontSize: 28, fontWeight: 650, letterSpacing: '-0.015em', color: C.text }}>{pct(c.severe_rate, 0)}</div>
                      <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>fell 40% or more within a year</div>
                    </div>
                    <span aria-hidden style={{ height: 8, borderRadius: 4, background: `color-mix(in srgb, ${C.rule} 70%, transparent)`, overflow: 'hidden' }}>
                      <span style={{ display: 'block', height: '100%', width: `${(c.severe_rate / maxSevere) * 100}%`, background: color, borderRadius: 4 }} />
                    </span>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.body, fontSize: 12, color: C.muted, borderTop: `1px solid ${C.rule}`, paddingTop: 10 }}>
                      <span>Volatility</span>
                      <span style={{ ...NUM, fontWeight: 600, color: C.text }}>{pct(c.realised_vol, 0)}</span>
                    </div>
                  </div>
                </Card>
              )
            })}
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Changes raised={raised} lowered={lowered} />
            <Card style={{ padding: '16px 18px' }}>
              <PanelTitle>What drives the grades</PanelTitle>
              <ul style={{ listStyle: 'none', margin: '14px 0 0', padding: 0, display: 'grid', gap: 14 }}>
                {pillars.map(([p, n]) => {
                  const Icon = PILLAR_ICON[p] ?? ShieldAlert
                  return (
                    <li key={p} style={{ display: 'grid', gridTemplateColumns: '30px minmax(0, 1fr)', gap: 10, alignItems: 'center' }}>
                      <span style={{ width: 30, height: 30, borderRadius: 9, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: C.accentSoft, color: C.accent }}>
                        <Icon size={15} />
                      </span>
                      <span style={{ minWidth: 0, display: 'grid', gap: 5 }}>
                        <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                          <span style={{ fontFamily: F.body, fontSize: 13.5, fontWeight: 600, color: C.text }}>{p}</span>
                          <span style={{ ...NUM, fontSize: 13, color: C.dim }}>
                            {n.toLocaleString()} <span style={{ color: C.muted }}>· {pct(n / pillarTotal, 0)}</span>
                          </span>
                        </span>
                        <span aria-hidden style={{ height: 6, borderRadius: 3, background: `color-mix(in srgb, ${C.rule} 70%, transparent)` }}>
                          <span style={{ display: 'block', height: '100%', width: `max(3px, ${(n / pillarTotal) * 100}%)`, background: C.accent, borderRadius: 3 }} />
                        </span>
                      </span>
                    </li>
                  )
                })}
              </ul>
            </Card>
          </div>

          {data.by_index && data.by_index.length > 1 && (
            <div className="grid gap-3 md:grid-cols-3">
              {data.by_index.map((b) => (
                <Card key={b.index} style={{ padding: 16, display: 'grid', gap: 12 }}>
                  <span style={{ fontFamily: F.body, fontSize: 15, fontWeight: 650, color: C.text }}>{b.index}</span>
                  <div>
                    <div style={{ ...NUM, fontSize: 26, fontWeight: 650, letterSpacing: '-0.015em', color: C.text }}>{pct(b.severe_rate, 0)}</div>
                    <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>of stocks fell 40% or more within a year</div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, borderTop: `1px solid ${C.rule}`, paddingTop: 10 }}>
                    <Mini label="Median volatility" value={pct(b.median_fwd_vol, 0)} />
                    <Mini label="Graded Severe" value={pct(b.share_graded_severe, 0)} />
                  </div>
                </Card>
              ))}
            </div>
          )}

          <ChartCard title="Grades by sector">
            <StackedBars rows={sectors} segments={GRADE_LABELS.map((label, i) => ({ label: `${i + 1} ${label}`, color: gradeColor(i + 1) }))} />
          </ChartCard>
        </>
      )}
    </Page>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="truncate" style={{ fontFamily: F.body, fontSize: 11.5, color: C.muted }}>
        {label}
      </div>
      <div style={{ ...NUM, fontSize: 14, fontWeight: 600, color: C.text, marginTop: 2 }}>{value}</div>
    </div>
  )
}

/** This month's grade changes, largest companies first: raised on one side, lowered on the other. */
function Changes({ raised, lowered }: { raised: WatchRow[]; lowered: WatchRow[] }) {
  const [all, setAll] = useState(false)
  const n = all ? Infinity : 6
  const column = (title: string, Icon: LucideIcon, rows: WatchRow[], color: string) => (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 12.5, fontWeight: 600, letterSpacing: '0.03em', textTransform: 'uppercase', color: C.muted, marginBottom: 4 }}>
        <Icon size={13} color={color} /> {title} <span style={{ ...NUM, color: C.dim }}>{rows.length}</span>
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {rows.slice(0, n).map((r) => (
          <li key={r.ticker}>
            <a href={`#/company/${encodeURIComponent(r.ticker)}`} className="hover-lift" style={{ display: 'grid', gridTemplateColumns: '32px minmax(0, 1fr) auto', gap: 10, alignItems: 'center', padding: '8px 6px', borderRadius: 8, border: '1px solid transparent', textDecoration: 'none', color: C.text }}>
              <Avatar ticker={r.ticker} name={r.name} size={32} />
              <span style={{ minWidth: 0 }}>
                <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 13.5, fontWeight: 600 }}>
                  {r.name ?? r.ticker}
                </span>
                <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 12, color: C.muted }}>
                  {r.ticker} · {r.risk_pillar ?? r.sector}
                </span>
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <GradeChip grade={r.previous_grade} compact />
                <ArrowRight size={13} color={C.muted} />
                <GradeChip grade={r.risk_grade} compact />
              </span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
  return (
    <Card style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 12 }}>
        <PanelTitle>Grade changes this month</PanelTitle>
        {(raised.length > 6 || lowered.length > 6) && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAll((a) => !a)}>
            {all ? 'Show fewer' : `Show all ${raised.length + lowered.length}`}
          </button>
        )}
      </div>
      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
        {column('Raised', ArrowUp, raised, gradeColor(5))}
        {column('Lowered', ArrowDown, lowered, gradeColor(1))}
      </div>
    </Card>
  )
}
