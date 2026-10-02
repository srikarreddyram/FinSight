import { ChartCard } from '../charts/core'
import { LineChart } from '../charts/LineChart'
import { Card, SectionLabel, Stat } from '../design/primitives'
import { C, CH, F, GRADE_LABELS, NUM } from '../design/tokens'
import { getCompany } from '../recs/api'
import { cap, num, pct } from '../recs/format'
import type { Driver } from '../recs/types'
import { link, useData } from './data'
import { BandBar, GradeChip, Page } from './shared'

function Drivers({ title, drivers, good }: { title: string; drivers: Driver[]; good: string }) {
  return (
    <Card style={{ padding: '16px 18px' }}>
      <SectionLabel style={{ letterSpacing: '0.24em' }}>{title}</SectionLabel>
      {drivers.length === 0 ? (
        <p style={{ fontFamily: F.body, fontSize: 13, color: C.muted, margin: '10px 0 0' }}>No single measure stands out.</p>
      ) : (
        <ol style={{ margin: '10px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: 10 }}>
          {drivers.map((d) => (
            <li key={d.signal} style={{ display: 'grid', gridTemplateColumns: '18px 1fr', gap: 8, alignItems: 'baseline' }}>
              <span aria-hidden style={{ ...NUM, fontSize: 13, color: d.effect === good ? CH.pos : CH.neg }}>
                {d.effect.startsWith('lifts') || d.effect.startsWith('raises') ? '▲' : '▼'}
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
  return (
    <Page
      title={card?.name && card.name !== card.ticker ? `${card.ticker} · ${card.name}` : ticker}
      lead={
        card ? (
          <>
            {card.sector ?? 'Sector unknown'} · market cap {cap(card.market_cap)} · <a href={link('/watchlist')} style={{ color: C.accent }}>back to the watchlist</a>
          </>
        ) : (
          'Loading the company card…'
        )
      }
      error={error}
      loading={!data}
    >
      {data && card && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card style={{ padding: '18px 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 20 }}>
                <Stat label="Return rank" value={card.return_rank.toFixed(0)} note="percentile of the universe this month" />
                <div>
                  <SectionLabel color={C.muted} style={{ letterSpacing: '0.22em' }}>
                    Past outcomes at this rank
                  </SectionLabel>
                  <div style={{ marginTop: 12 }}>
                    <BandBar band={card.band} />
                  </div>
                  {card.band && (
                    <div style={{ fontFamily: F.mono, fontSize: 10.5, color: C.muted, marginTop: 6, lineHeight: 1.6 }}>
                      middle half {pct(card.band.p25, 0, true)} to {pct(card.band.p75, 0, true)} vs the S&amp;P 500 over 12 months
                    </div>
                  )}
                </div>
              </div>
              <p style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, margin: '14px 0 0', lineHeight: 1.6 }}>
                The range is what stocks ranked in the same tenth actually did in 2015–2024. It is wide at every rank and barely differs between ranks: in testing, the model’s edge was not distinguishable from zero.
              </p>
            </Card>
            <Card style={{ padding: '18px 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 20 }}>
                <div>
                  <SectionLabel color={C.muted} style={{ letterSpacing: '0.22em' }}>
                    Risk grade
                  </SectionLabel>
                  <div style={{ marginTop: 10, transform: 'scale(1.25)', transformOrigin: 'left center' }}>
                    <GradeChip grade={card.risk_grade} />
                  </div>
                  <div style={{ fontFamily: F.mono, fontSize: 10.5, color: C.muted, marginTop: 10 }}>
                    {card.previous_grade != null && card.previous_grade !== card.risk_grade ? `was ${card.previous_grade} ${GRADE_LABELS[card.previous_grade - 1]} last month` : 'unchanged from last month'}
                  </div>
                </div>
                <Stat label="Volatility" value={pct(card.expected_vol, 0)} note={`past year: ${pct(card.vol_12m, 0)}`} delay={60} />
                <Stat label="Severe-loss rate" value={pct(card.severe_loss_rate, 0)} note="fell 40%+ within a year" delay={120} />
              </div>
              <p style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, margin: '14px 0 0', lineHeight: 1.6 }}>
                Both figures are what happened to stocks ranked in the same tenth in 2015–2024. Main driver: {card.risk_pillar ? `${card.risk_pillar}${card.risk_pillar_effect ? ` (${card.risk_pillar_effect})` : ''}` : 'not determined'}.
              </p>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Drivers title="What moves the return rank" drivers={card.return_drivers} good="lifts the rank" />
            <Drivers title="What moves the risk grade" drivers={card.risk_drivers} good="lowers risk" />
          </div>

          <Card style={{ padding: '14px 18px' }}>
            <SectionLabel color={C.muted} style={{ letterSpacing: '0.24em' }}>
              Read the filing
            </SectionLabel>
            <p style={{ fontFamily: F.body, fontSize: 13.5, color: C.dim, margin: '8px 0 0', lineHeight: 1.6 }}>
              {hasFilings ? (
                <>
                  This company’s filings are indexed.{' '}
                  <a href={`/?q=${encodeURIComponent(`What are the main risk factors for ${card.name ?? card.ticker}?`)}`} style={{ color: C.accent }}>
                    Ask the Copilot about {card.name ?? card.ticker}
                  </a>{' '}
                  and get answers cited to the page.
                </>
              ) : (
                'This company’s filings are not in the Copilot’s index yet, so there is no cited thesis for it. The Analyst Agent’s thesis and the XBRL cross-check of each figure are planned and not built.'
              )}
            </p>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Return rank over time" note="The model’s percentile rank each month in the walk-forward test years (each year predicted by a model trained only on earlier years).">
              <LineChart x={data.return_history.map((r) => r.month.slice(0, 7))} series={[{ name: 'Return rank', color: C.accent, values: data.return_history.map((r) => r.return_rank) }]} format={(v) => v.toFixed(0)} domain={[0, 100]} height={210} endLabels={false} />
            </ChartCard>
            <ChartCard title="What happened next" note="The stock’s return over the 12 months after each month, minus the S&P 500’s.">
              <LineChart x={data.return_history.map((r) => r.month.slice(0, 7))} series={[{ name: '12-month excess return', color: C.computed, values: data.return_history.map((r) => r.excess_ret) }]} format={(v) => pct(v, 0, true)} zero height={210} endLabels={false} />
            </ChartCard>
          </div>

          <ChartCard title="Risk grade over time" note="Grade each month in the walk-forward test years: 1 Low to 5 Severe.">
            <LineChart x={data.risk_history.map((r) => r.month.slice(0, 7))} series={[{ name: 'Risk grade', color: 'var(--grade-3)', values: data.risk_history.map((r) => r.grade) }]} format={(v) => (Number.isInteger(v) ? `${v} ${GRADE_LABELS[v - 1] ?? ''}` : num(v, 1))} axisFormat={(v) => String(v)} domain={[0.6, 5.4]} tickValues={[1, 2, 3, 4, 5]} step height={200} endLabels={false} />
          </ChartCard>

          <Card style={{ padding: '16px 18px' }}>
            <SectionLabel style={{ letterSpacing: '0.24em' }}>Signal history</SectionLabel>
            <p style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, margin: '6px 0 14px', lineHeight: 1.55 }}>
              Each signal as a percentile of the universe that month (100 = highest value), using only what had been filed by then.
            </p>
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
