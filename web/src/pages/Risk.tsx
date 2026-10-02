import { useMemo } from 'react'
import { ChartCard } from '../charts/core'
import { ColumnChart } from '../charts/ColumnChart'
import { StackedBars } from '../charts/StackedBars'
import { Card, SectionLabel, Stat } from '../design/primitives'
import { C, F, GRADE_LABELS, gradeColor } from '../design/tokens'
import { getRisk, getWatchlist } from '../recs/api'
import { num, pct } from '../recs/format'
import { link, useData } from './data'
import { GradeChip, Page, StatRow } from './shared'

export function Risk() {
  const { data, error } = useData(getRisk)
  const { data: watch } = useData(getWatchlist)
  const o = data?.overall ?? {}
  const sectors = useMemo(() => {
    const by = new Map<string, number[]>()
    for (const d of data?.distribution ?? []) {
      const row = by.get(d.sector) ?? [0, 0, 0, 0, 0]
      row[d.risk_grade - 1] = d.n
      by.set(d.sector, row)
    }
    return [...by.entries()].map(([label, counts]) => ({ label, counts })).sort((a, b) => a.label.localeCompare(b.label))
  }, [data])
  const changes = useMemo(
    () => (watch ?? []).filter((r) => r.risk_grade != null && r.previous_grade != null && r.risk_grade !== r.previous_grade).sort((a, b) => (b.risk_grade! - b.previous_grade!) - (a.risk_grade! - a.previous_grade!)),
    [watch],
  )
  const pillars = Object.entries(data?.pillars ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <Page
      title="Risk"
      lead="Every company gets a grade from 1 (Low) to 5 (Severe) each month, from two things: how volatile the stock is expected to be over the next year, and how likely a fall of 40% or more is. It is a research measure, not a credit rating."
      error={error}
      loading={!data}
    >
      {data && (
        <>
          <StatRow>
            <Stat label="Severe-loss rate, grade 5" value={pct(data.calibration[4]?.severe_rate, 0)} note={`vs ${pct(data.calibration[0]?.severe_rate, 0)} for grade 1`} />
            <Stat label="Volatility, grade 5" value={pct(data.calibration[4]?.realised_vol, 0)} note={`vs ${pct(data.calibration[0]?.realised_vol, 0)} for grade 1`} delay={60} />
            <Stat label="Downside AUC" value={num(o.monthly_auc_model, 2)} note={`within month; trailing volatility alone: ${num(o.monthly_auc_trailing_vol, 2)}`} delay={120} />
            <Stat label="Volatility rank IC" value={num(o.vol_ic_model, 2)} note={`trailing volatility alone: ${num(o.vol_ic_trailing, 2)}`} delay={180} />
            <Stat label="Grades that change" value={pct(data.grade_change_rate, 0)} note="of companies, month to month" delay={240} />
          </StatRow>

          <Card accent={C.warn} style={{ padding: '14px 18px' }}>
            <SectionLabel color={C.warn}>What the validation says</SectionLabel>
            <p style={{ fontFamily: F.body, fontSize: 13.5, color: C.dim, margin: '8px 0 0', lineHeight: 1.65, maxWidth: 900 }}>
              The grades sort risk well: every step up has gone with higher volatility and more severe losses. But the models behind them do not beat a much simpler measure, the stock’s own volatility over the past year, which the product spec set as the bar. Read the grade as mostly “how volatile has this stock been”, with the filing measures as context, until that bar is cleared.
            </p>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard
              title="Severe-loss rate by grade"
              note="Share of stock-months in each grade that went on to fall 40% or more within 12 months, test years 2015–2024."
              table={<CalibrationTable rows={data.calibration} />}
            >
              <ColumnChart name="Severe-loss rate" categories={[...GRADE_LABELS]} values={data.calibration.map((c) => c.severe_rate)} color={(_, i) => gradeColor(i + 1)} format={(v) => pct(v, 0)} />
            </ChartCard>
            <ChartCard title="Realised volatility by grade" note="Average annualised volatility over the following 12 months, same test years." table={<CalibrationTable rows={data.calibration} />}>
              <ColumnChart name="Realised volatility" categories={[...GRADE_LABELS]} values={data.calibration.map((c) => c.realised_vol)} color={(_, i) => gradeColor(i + 1)} format={(v) => pct(v, 0)} />
            </ChartCard>
          </div>

          <ChartCard title="Grades this month, by sector" note="Grades are ranked across the whole universe, so a sector can sit mostly at one end.">
            <StackedBars rows={sectors} segments={GRADE_LABELS.map((label, i) => ({ label: `${i + 1} ${label}`, color: gradeColor(i + 1) }))} />
          </ChartCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card style={{ padding: '16px 18px' }}>
              <SectionLabel style={{ letterSpacing: '0.24em' }}>Models against baselines</SectionLabel>
              <table className="dash-table" style={{ marginTop: 10 }}>
                <thead>
                  <tr>
                    <th className="left">Measure</th>
                    <th>Model</th>
                    <th>Trailing volatility</th>
                    <th>Scorecard</th>
                    <th>Altman Z</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="left">Volatility rank IC</td>
                    <td>{num(o.vol_ic_model, 3)}</td>
                    <td>{num(o.vol_ic_trailing, 3)}</td>
                    <td>{num(o.vol_ic_scorecard, 3)}</td>
                    <td>–</td>
                  </tr>
                  <tr>
                    <td className="left">Downside AUC, within month</td>
                    <td>{num(o.monthly_auc_model, 3)}</td>
                    <td>{num(o.monthly_auc_trailing_vol, 3)}</td>
                    <td>{num(o.monthly_auc_scorecard, 3)}</td>
                    <td>{num(o.monthly_auc_altman_z, 3)}</td>
                  </tr>
                  <tr>
                    <td className="left">Severe-loss rate, riskiest 10%</td>
                    <td>{pct(o.top10_severe_model, 1)}</td>
                    <td>{pct(o.top10_severe_trailing_vol, 1)}</td>
                    <td>{pct(o.top10_severe_scorecard, 1)}</td>
                    <td>–</td>
                  </tr>
                </tbody>
              </table>
              <p style={{ fontFamily: F.body, fontSize: 12, color: C.muted, margin: '10px 0 0', lineHeight: 1.55 }}>
                Base rate of a severe loss: {pct(o.base_severe_rate, 1)}. AUC of 0.5 is a coin flip.
              </p>
            </Card>
            <Card style={{ padding: '16px 18px' }}>
              <SectionLabel style={{ letterSpacing: '0.24em' }}>Main driver of each company’s risk, this month</SectionLabel>
              <table className="dash-table" style={{ marginTop: 10 }}>
                <thead>
                  <tr>
                    <th className="left">Pillar</th>
                    <th>Companies</th>
                  </tr>
                </thead>
                <tbody>
                  {pillars.map(([p, n]) => (
                    <tr key={p}>
                      <td className="left">{p}</td>
                      <td>{n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>

          <Card style={{ overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px 4px' }}>
              <SectionLabel style={{ letterSpacing: '0.24em' }}>Grade changes since last month</SectionLabel>
            </div>
            <div style={{ overflow: 'auto', maxHeight: 360 }}>
              <table className="dash-table">
                <thead>
                  <tr>
                    <th className="left">Company</th>
                    <th className="left">Sector</th>
                    <th className="left">Last month</th>
                    <th className="left">This month</th>
                    <th className="left">Main driver</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((r) => (
                    <tr key={r.ticker}>
                      <td className="left">
                        <a href={link(`/company/${r.ticker}`)} style={{ color: C.accent, textDecoration: 'none', fontWeight: 600 }}>
                          {r.ticker}
                        </a>{' '}
                        <span style={{ fontFamily: F.body, color: C.muted }}>{r.name}</span>
                      </td>
                      <td className="left" style={{ fontFamily: F.body, color: C.dim }}>
                        {r.sector}
                      </td>
                      <td className="left">
                        <GradeChip grade={r.previous_grade} />
                      </td>
                      <td className="left">
                        <GradeChip grade={r.risk_grade} />
                      </td>
                      <td className="left" style={{ fontFamily: F.body, color: C.dim }}>
                        {r.risk_pillar}
                        {r.risk_pillar_effect ? ` (${r.risk_pillar_effect})` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </Page>
  )
}

function CalibrationTable({ rows }: { rows: { grade: string; n: number; realised_vol: number; severe_rate: number }[] }) {
  return (
    <table className="dash-table">
      <thead>
        <tr>
          <th className="left">Grade</th>
          <th>Stock-months</th>
          <th>Realised volatility</th>
          <th>Severe-loss rate</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.grade}>
            <td className="left">
              <GradeChip grade={i + 1} />
            </td>
            <td>{r.n.toLocaleString()}</td>
            <td>{pct(r.realised_vol, 1)}</td>
            <td>{pct(r.severe_rate, 1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
