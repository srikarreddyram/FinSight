import { ChartCard } from '../charts/core'
import { ColumnChart } from '../charts/ColumnChart'
import { LineChart } from '../charts/LineChart'
import { Card, PanelTitle, Stat } from '../design/primitives'
import { C, CH } from '../design/tokens'
import { getBacktest } from '../recs/api'
import { monthLabel, num, pct } from '../recs/format'
import type { BacktestMonth } from '../recs/types'
import { useData } from './data'
import { Page, StatRow } from './shared'

const NAMES: Record<string, string> = {
  lgbm: 'LightGBM ranker',
  best_signal: 'Best single signal',
  linear: 'Ridge regression',
  fscore: 'F-score alone',
  random: 'Random ranks',
}

function cumulative(months: BacktestMonth[], key: 'long_short' | 'long_short_net'): number[] {
  let w = 1
  return months.map((m) => (w *= 1 + m[key]) - 1)
}

function drawdown(months: BacktestMonth[]): number[] {
  let w = 1
  let peak = 1
  return months.map((m) => {
    w *= 1 + m.long_short_net
    peak = Math.max(peak, w)
    return w / peak - 1
  })
}

export function Backtest() {
  const { data, error } = useData(getBacktest)
  const model = data?.models.lgbm
  const names = data ? Object.keys(data.models) : []
  const net = model?.stats.long_short_net
  return (
    <Page
      title="Backtest"
      error={error}
      loading={!data}
    >
      {data && model && net && (
        <>
          <StatRow>
            <Stat label="Annual return" value={`${pct(net.ann_return, 1, true)}`} note="long-short, after costs" />
            <Stat label="Sharpe ratio" value={num(net.sharpe, 2)} note={`${net.months} months`} />
            <Stat label="Max drawdown" value={pct(net.max_drawdown, 0)} />
            <Stat label="Monthly turnover" value={num(net.avg_turnover, 2)} note={`${data.cost_bps} bps per trade`} />
            <Stat label="Mean rank IC" value={num(model.mean_ic, 3)} />
          </StatRow>

          <ChartCard
            title="Cumulative return, after costs"
            table={
              <table className="dash-table">
                <thead>
                  <tr>
                    <th className="left">Model</th>
                    <th>Before costs</th>
                    <th>After costs</th>
                    <th>Volatility</th>
                    <th>Sharpe</th>
                    <th>Max drawdown</th>
                    <th>Turnover</th>
                    <th>Mean IC</th>
                  </tr>
                </thead>
                <tbody>
                  {names.map((n) => {
                    const m = data.models[n]
                    return (
                      <tr key={n}>
                        <td className="left">{NAMES[n] ?? n}</td>
                        <td>{pct(m.stats.long_short.ann_return, 1, true)}</td>
                        <td>{pct(m.stats.long_short_net.ann_return, 1, true)}</td>
                        <td>{pct(m.stats.long_short_net.ann_vol, 1)}</td>
                        <td>{num(m.stats.long_short_net.sharpe, 2)}</td>
                        <td>{pct(m.stats.long_short_net.max_drawdown, 0)}</td>
                        <td>{num(m.stats.long_short_net.avg_turnover, 2)}</td>
                        <td>{num(m.mean_ic, 3)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            }
          >
            <LineChart
              x={model.monthly.map((m) => m.month.slice(0, 7))}
              format={(v) => pct(v, 0, true)}
              zero
              series={names.map((n) => ({
                name: NAMES[n] ?? n,
                color: n === 'lgbm' ? C.accent : CH.context,
                context: n !== 'lgbm',
                values: cumulative(data.models[n].monthly, 'long_short_net'),
              }))}
            />
          </ChartCard>

          {data.by_index && data.by_index.length > 1 && (
            <Card style={{ padding: '16px 18px', overflowX: 'auto' }}>
              <PanelTitle>By index</PanelTitle>
              <table className="dash-table" style={{ marginTop: 10 }}>
                <thead>
                  <tr>
                    <th className="left">Index</th>
                    <th>Since</th>
                    <th>Companies</th>
                    <th>Rank IC</th>
                    <th>Before costs</th>
                    <th>After costs</th>
                    <th>Sharpe</th>
                    <th>Max drawdown</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_index.map((b) => (
                    <tr key={b.index}>
                      <td className="left">{b.index}</td>
                      <td>{monthLabel(b.from)}</td>
                      <td>{b.companies}</td>
                      <td>{num(b.mean_ic.lgbm, 3, true)}</td>
                      <td>{pct(b.stats.long_short.ann_return, 1, true)}</td>
                      <td>{pct(b.stats.long_short_net.ann_return, 1, true)}</td>
                      <td>{num(b.stats.long_short_net.sharpe, 2)}</td>
                      <td>{pct(b.stats.long_short_net.max_drawdown, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChartCard
              title="Return by year, after costs"
              table={
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th className="left">Year</th>
                      <th>Before costs</th>
                      <th>After costs</th>
                      <th>S&amp;P 500</th>
                      <th>Rank IC</th>
                    </tr>
                  </thead>
                  <tbody>
                    {model.by_year.map((y) => (
                      <tr key={y.year}>
                        <td className="left">{y.year}</td>
                        <td>{pct(y.long_short, 1, true)}</td>
                        <td>{pct(y.long_short_net, 1, true)}</td>
                        <td>{pct(y.bench, 1, true)}</td>
                        <td>{num(y.ic, 3, true)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              }
            >
              <ColumnChart
                name="Long-short return after costs"
                categories={model.by_year.map((y) => String(y.year))}
                values={model.by_year.map((y) => y.long_short_net)}
                color={(v) => (v >= 0 ? CH.pos : CH.neg)}
                format={(v) => pct(v, 0, true)}
              />
            </ChartCard>
            <ChartCard title="Drawdown, after costs">
              <LineChart
                x={model.monthly.map((m) => m.month.slice(0, 7))}
                format={(v) => pct(v, 0)}
                zero
                area
                endLabels={false}
                height={220}
                series={[{ name: 'Drawdown', color: CH.neg, values: drawdown(model.monthly) }]}
              />
            </ChartCard>
          </div>
        </>
      )}
    </Page>
  )
}
