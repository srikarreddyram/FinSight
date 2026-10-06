import { useMemo } from 'react'
import { ChartCard } from '../charts/core'
import { ColumnChart } from '../charts/ColumnChart'
import { StackedBars } from '../charts/StackedBars'
import { Card, PanelTitle, Stat } from '../design/primitives'
import { C, F, GRADE_LABELS, gradeColor } from '../design/tokens'
import { getRisk, getWatchlist } from '../recs/api'
import { pct } from '../recs/format'
import { link, useData } from './data'
import { GradeChip, Page, StatRow } from './shared'

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
  const changes = useMemo(
    () => (watch ?? []).filter((r) => r.risk_grade != null && r.previous_grade != null && r.risk_grade !== r.previous_grade).sort((a, b) => (b.risk_grade! - b.previous_grade!) - (a.risk_grade! - a.previous_grade!)),
    [watch],
  )
  const severe = (watch ?? []).filter((r) => r.risk_grade === 5).length
  const upgrades = changes.filter((r) => r.risk_grade! > r.previous_grade!).length
  const pillars = Object.entries(data?.pillars ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <Page title="Risk" error={error} loading={!data}>
      {data && (
        <>
          <StatRow>
            <Stat label="Graded Severe" value={watch ? severe.toLocaleString() : '–'} note="companies this month" />
            <Stat label="Grade changes" value={watch ? changes.length.toLocaleString() : '–'} note={watch ? `${upgrades} up, ${changes.length - upgrades} down` : undefined} />
            <Stat label="Severe-loss rate, grade 5" value={pct(data.calibration[4]?.severe_rate, 0)} note={`${pct(data.calibration[0]?.severe_rate, 0)} for grade 1`} />
            <Stat label="Volatility, grade 5" value={pct(data.calibration[4]?.realised_vol, 0)} note={`${pct(data.calibration[0]?.realised_vol, 0)} for grade 1`} />
          </StatRow>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChartCard title="Severe-loss rate by grade" table={<CalibrationTable rows={data.calibration} />}>
              <ColumnChart name="Severe-loss rate" categories={[...GRADE_LABELS]} values={data.calibration.map((c) => c.severe_rate)} color={(_, i) => gradeColor(i + 1)} format={(v) => pct(v, 0)} />
            </ChartCard>
            <ChartCard title="Realised volatility by grade" table={<CalibrationTable rows={data.calibration} />}>
              <ColumnChart name="Realised volatility" categories={[...GRADE_LABELS]} values={data.calibration.map((c) => c.realised_vol)} color={(_, i) => gradeColor(i + 1)} format={(v) => pct(v, 0)} />
            </ChartCard>
          </div>

          <ChartCard title="Grades by sector">
            <StackedBars rows={sectors} segments={GRADE_LABELS.map((label, i) => ({ label: `${i + 1} ${label}`, color: gradeColor(i + 1) }))} />
          </ChartCard>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {data.by_index && data.by_index.length > 1 && (
              <Card style={{ padding: '14px 18px 16px', minWidth: 0, overflowX: 'auto' }}>
                <PanelTitle>By index</PanelTitle>
                <table className="dash-table" style={{ marginTop: 10 }}>
                  <thead>
                    <tr>
                      <th className="left">Index</th>
                      <th>Severe-loss rate</th>
                      <th>Median volatility</th>
                      <th>Graded Severe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_index.map((b) => (
                      <tr key={b.index}>
                        <td className="left">{b.index}</td>
                        <td>{pct(b.severe_rate, 1)}</td>
                        <td>{pct(b.median_fwd_vol, 0)}</td>
                        <td>{pct(b.share_graded_severe, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            )}
            <Card style={{ padding: '14px 18px 16px', minWidth: 0 }}>
              <PanelTitle>Main risk driver</PanelTitle>
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
                      <td>{n.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>

          <Card style={{ overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px 10px' }}>
              <PanelTitle>Grade changes this month</PanelTitle>
            </div>
            <div style={{ overflow: 'auto', maxHeight: 420 }}>
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
