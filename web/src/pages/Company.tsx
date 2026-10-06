import { ArrowDownRight, ArrowLeft, ArrowUpRight, MessageSquareText } from 'lucide-react'
import { ChartCard } from '../charts/core'
import { LineChart } from '../charts/LineChart'
import { Badge, Card, PanelTitle, SectionLabel, Stat } from '../design/primitives'
import { C, CH, F, GRADE_LABELS, NUM } from '../design/tokens'
import { getCompany } from '../recs/api'
import { cap, num, pct } from '../recs/format'
import type { Driver } from '../recs/types'
import { useData } from './data'
import { BandBar, GradeChip, Page } from './shared'

function Drivers({ title, drivers, good }: { title: string; drivers: Driver[]; good: string }) {
  return (
    <Card style={{ padding: '16px 18px' }}>
      <PanelTitle>{title}</PanelTitle>
      {drivers.length === 0 ? (
        <p style={{ fontFamily: F.body, fontSize: 13, color: C.muted, margin: '10px 0 0' }}>No single measure stands out.</p>
      ) : (
        <ol style={{ margin: '10px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 10 }}>
          {drivers.map((d) => (
            <li key={d.signal} style={{ display: 'grid', gridTemplateColumns: '18px 1fr', gap: 8, alignItems: 'start' }}>
              <span aria-hidden style={{ display: 'flex', color: d.effect === good ? CH.pos : CH.neg, transform: 'translateY(2px)' }}>
                {d.effect.startsWith('lifts') || d.effect.startsWith('raises') ? <ArrowUpRight size={15} strokeWidth={2.4} /> : <ArrowDownRight size={15} strokeWidth={2.4} />}
              </span>
              <span style={{ fontFamily: F.body, fontSize: 13.5, color: C.text, lineHeight: 1.5 }}>
                {d.text}
                <span style={{ color: C.muted }}> · {d.effect}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

export function Company({ ticker, hasFilings }: { ticker: string; hasFilings: boolean }) {
  const { data, error } = useData(() => getCompany(ticker), ticker)
  const card = data?.card
  const months = (data?.signal_history ?? []).map((r) => String(r.month).slice(0, 7))
  const name = card?.name && card.name !== card.ticker ? card.name : ticker
  const askHref = `/?q=${encodeURIComponent(`What are the main risk factors for ${card?.name ?? ticker}?`)}`
  return (
    <Page
      title={
        <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          {name}
          {name !== ticker && <span style={{ ...NUM, fontSize: 15, fontWeight: 600, color: C.accent }}>{ticker}</span>}
        </span>
      }
      meta={
        card && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {card.index && <Badge tone="accent">{card.index}</Badge>}
            <Badge>{card.sector ?? 'Sector unknown'}</Badge>
            <Badge>Market cap {cap(card.market_cap)}</Badge>
          </div>
        )
      }
      aside={
        card && (
          <div style={{ display: 'flex', gap: 8 }}>
            <a href="#/watchlist" className="btn btn-secondary">
              <ArrowLeft size={15} /> Watchlist
            </a>
            {hasFilings && (
              <a href={askHref} className="btn btn-primary">
                <MessageSquareText size={15} /> Ask the Copilot
              </a>
            )}
          </div>
        )
      }
      error={error}
      loading={!data}
    >
      {data && card && (
        <>
          <Card style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 1, background: C.rule }}>
              <div style={{ background: C.surface, padding: '16px 18px' }}>
                <Stat label="Return rank" value={card.return_rank.toFixed(0)} note="percentile" />
              </div>
              <div style={{ background: C.surface, padding: '16px 18px' }}>
                <SectionLabel>Expected range</SectionLabel>
                <div style={{ marginTop: 12 }}>
                  <BandBar band={card.band} />
                </div>
                {card.band && (
                  <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 8, lineHeight: 1.45 }}>
                    {pct(card.band.p25, 0, true)} to {pct(card.band.p75, 0, true)} vs S&amp;P 500, 12 months
                  </div>
                )}
              </div>
              <div style={{ background: C.surface, padding: '16px 18px' }}>
                <SectionLabel>Risk grade</SectionLabel>
                <div style={{ marginTop: 10, transform: 'scale(1.2)', transformOrigin: 'left center' }}>
                  <GradeChip grade={card.risk_grade} />
                </div>
                <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 10 }}>
                  {card.previous_grade != null && card.previous_grade !== card.risk_grade ? `was ${card.previous_grade} ${GRADE_LABELS[card.previous_grade - 1]} last month` : 'unchanged'}
                </div>
              </div>
              <div style={{ background: C.surface, padding: '16px 18px' }}>
                <Stat label="Expected volatility" value={pct(card.expected_vol, 0)} note={`past year ${pct(card.vol_12m, 0)}`} />
              </div>
              <div style={{ background: C.surface, padding: '16px 18px' }}>
                <Stat label="Severe-loss risk" value={pct(card.severe_loss_rate, 0)} note="fall of 40%+ in a year" />
              </div>
            </div>
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Drivers title="Return drivers" drivers={card.return_drivers} good="lifts the rank" />
            <Drivers title="Risk drivers" drivers={card.risk_drivers} good="lowers risk" />
          </div>


          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChartCard title="Return rank">
              <LineChart x={data.return_history.map((r) => r.month.slice(0, 7))} series={[{ name: 'Return rank', color: C.accent, values: data.return_history.map((r) => r.return_rank) }]} format={(v) => v.toFixed(0)} domain={[0, 100]} height={210} endLabels={false} />
            </ChartCard>
            <ChartCard title="12-month return vs S&P 500">
              <LineChart x={data.return_history.map((r) => r.month.slice(0, 7))} series={[{ name: '12-month excess return', color: C.computed, values: data.return_history.map((r) => r.excess_ret) }]} format={(v) => pct(v, 0, true)} zero height={210} endLabels={false} />
            </ChartCard>
          </div>

          <ChartCard title="Risk grade">
            <LineChart x={data.risk_history.map((r) => r.month.slice(0, 7))} series={[{ name: 'Risk grade', color: 'var(--grade-3)', values: data.risk_history.map((r) => r.grade) }]} format={(v) => (Number.isInteger(v) ? `${v} ${GRADE_LABELS[v - 1] ?? ''}` : num(v, 1))} axisFormat={(v) => String(v)} domain={[0.6, 5.4]} tickValues={[1, 2, 3, 4, 5]} step height={200} endLabels={false} />
          </ChartCard>

          <Card style={{ padding: '16px 18px' }}>
            <PanelTitle style={{ marginBottom: 14 }}>Signals (percentile)</PanelTitle>
            <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
              {data.signals.map((s) => (
                <div key={s.signal} style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: F.body, fontSize: 12.5, color: C.text, fontWeight: 600 }}>{s.label}</div>
                  <LineChart
                    x={months}
                    series={[{ name: s.label, color: C.accent, values: data.signal_history.map((r) => (typeof r[`${s.signal}_rank`] === 'number' ? (r[`${s.signal}_rank`] as number) * 100 : null)) }]}
                    format={(v) => v.toFixed(0)}
                    domain={[0, 100]}
                    tickValues={[0, 50, 100]}
                    height={120}
                    endLabels={false}
                  />
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </Page>
  )
}
