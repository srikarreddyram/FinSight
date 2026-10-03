import { ChartCard } from '../charts/core'
import { ColumnChart } from '../charts/ColumnChart'
import { LineChart } from '../charts/LineChart'
import { Card, SectionLabel, Stat } from '../design/primitives'
import { C, CH, F } from '../design/tokens'
import { getBacktest } from '../recs/api'
import { num, pct } from '../recs/format'
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
  const best = model ? [...model.by_year].sort((a, b) => b.long_short_net - a.long_short_net)[0] : undefined
  const withoutBest = model && best ? model.by_year.filter((y) => y !== best).reduce((w, y) => w * (1 + y.long_short_net), 1) - 1 : 0
  return (
    <Page
      title="Backtest"
      lead="Each month the model ranks the universe on information public by month end. The test buys the top tenth, sells the bottom tenth, holds one month and deducts trading costs. Every year shown was predicted by a model trained only on earlier years."
      error={error}
      loading={!data}
    >
      {data && model && net && (
        <>
          <StatRow>
            <Stat label="Return after costs" value={`${pct(net.ann_return, 1, true)}`} note="a year, top minus bottom tenth" />
            <Stat label="Sharpe ratio" value={num(net.sharpe, 2)} note={`${net.months} months, 2015–2024`} delay={60} />
            <Stat label="Worst drawdown" value={pct(net.max_drawdown, 0)} note="peak to trough, after costs" delay={120} />
            <Stat label="Monthly turnover" value={num(net.avg_turnover, 2)} note={`of a maximum 4; ${data.cost_bps} bps per trade`} delay={180} />
            <Stat label="Mean rank IC" value={num(Math.abs(model.mean_ic) < 0.0005 ? 0 : model.mean_ic, 3)} note="monthly, 12-month excess return" delay={240} />
          </StatRow>

          <ChartCard
            title="Cumulative long-short return, after costs"
            note="The ranker against four baselines scored the same way. Random ranks should lose roughly their trading costs, and do."
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
            <p style={{ fontFamily: F.body, fontSize: 12, color: C.muted, margin: '10px 0 0', lineHeight: 1.55 }}>
              A Sharpe ratio this size over ten years is within what chance produces, so this is not evidence of skill.
              {best && ` Its best year, ${best.year} (${pct(best.long_short_net, 0, true)}), carries the result: the other years compound to ${pct(withoutBest, 0, true)}.`} Baselines share one gray on purpose: the question is whether the ranker separates from them, not which baseline is which. The table view lists each one.
            </p>
          </ChartCard>

          {data.by_index && data.by_index.length > 1 && (
            <Card style={{ padding: '16px 18px', overflowX: 'auto' }}>
              <SectionLabel style={{ letterSpacing: '0.24em' }}>The same test inside each index</SectionLabel>
              <table className="dash-table" style={{ marginTop: 10 }}>
                <thead>
                  <tr>
                    <th className="left">Index</th>
                    <th title="First month the index's members are in the test">Tested from</th>
                    <th title="Median number of companies ranked each month">Companies</th>
                    <th title="Mean monthly rank IC of the LightGBM ranker, within the index">Ranker IC</th>
                    <th title="Mean monthly rank IC of the ridge regression, within the index">Ridge IC</th>
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
                      <td>{b.from.slice(0, 7)}</td>
                      <td>{b.companies}</td>
                      <td>{num(b.mean_ic.lgbm, 3, true)}</td>
                      <td>{num(b.mean_ic.linear, 3, true)}</td>
                      <td>{pct(b.stats.long_short.ann_return, 1, true)}</td>
                      <td>{pct(b.stats.long_short_net.ann_return, 1, true)}</td>
                      <td>{num(b.stats.long_short_net.sharpe, 2)}</td>
                      <td>{pct(b.stats.long_short_net.max_drawdown, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.checks && (
                <table className="dash-table" style={{ marginTop: 14 }}>
                  <thead>
                    <tr>
                      <th className="left">Ranker IC, by index</th>
                      <th title="Mean monthly rank IC of the ranker's predictions">As predicted</th>
                      <th title="t-statistic on yearly mean ICs">t</th>
                      <th title="IC of what is left of the prediction after removing size, past-year volatility, past-year return and beta, month by month">Style removed</th>
                      <th title="t-statistic on yearly mean ICs">t</th>
                      <th title="Stock-months in the test years whose outcome is known but that have no return: companies later acquired or delisted">No return</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...new Set(data.checks.ic.map((r) => r.universe))].map((u) => {
                      const raw = data.checks!.ic.find((r) => r.universe === u && r.model === 'lgbm' && r.kind === 'raw')
                      const neutral = data.checks!.ic.find((r) => r.universe === u && r.model === 'lgbm' && r.kind === 'neutral')
                      const gap = u === 'All indexes' ? undefined : data.checks!.unscored[u]
                      return (
                        <tr key={u}>
                          <td className="left">{u}</td>
                          <td>{num(raw?.ic, 3, true)}</td>
                          <td>{num(raw?.t, 1, true)}</td>
                          <td>{num(neutral?.ic, 3, true)}</td>
                          <td>{num(neutral?.t, 1, true)}</td>
                          <td>{pct(gap, 0)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
              <p style={{ fontFamily: F.body, fontSize: 12, color: C.muted, margin: '10px 0 0', lineHeight: 1.55 }}>
                One model, trained on all three indexes; here its top and bottom tenths are formed among one index’s members only. The smaller indexes have shorter histories, so their rows rest on fewer months.
              </p>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard
              title="Return by year, after costs"
              note="Bad years stay visible: an average hides them."
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
            <ChartCard title="Drawdown, after costs" note="How far the long-short portfolio sat below its previous high.">
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
