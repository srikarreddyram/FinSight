// Backtest: the long-short strategy as a growth-of-$10,000 chart, its key figures, how it compares with the
// baselines, how it did inside each index, and each year's result with its drawdowns.
import { Activity, ArrowDownRight, Gauge, Repeat, Sigma, TrendingUp, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { ChartCard } from '../charts/core'
import { LineChart } from '../charts/LineChart'
import { Card, PanelTitle, Segmented } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getBacktest } from '../recs/api'
import { monthLabel, num, pct } from '../recs/format'
import type { BacktestMonth } from '../recs/types'
import { useData } from './data'
import { Page } from './shared'

const NAMES: Record<string, string> = {
  lgbm: 'LightGBM ranker',
  best_signal: 'Best single signal',
  linear: 'Ridge regression',
  fscore: 'F-score alone',
  random: 'Random ranks',
}
const START = 10_000
const tone = (v: number | null | undefined) => (v == null || v === 0 ? C.muted : v > 0 ? CH.pos : CH.neg)
const dollars = (v: number) => `$${Math.round(v).toLocaleString('en-US')}`

function growth(months: BacktestMonth[], key: 'long_short_net' | 'bench'): number[] {
  let w = START
  return months.map((m) => (w *= 1 + m[key]))
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

type Compare = 'none' | 'bench' | 'models'

export function Backtest() {
  const { data, error } = useData(getBacktest)
  const [compare, setCompare] = useState<Compare>('none')
  const model = data?.models.lgbm
  const net = model?.stats.long_short_net
  const names = data ? Object.keys(data.models) : []

  return (
    <Page title="Backtest" meta={model ? <span style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>Long the top tenth, short the bottom tenth · monthly · {data?.cost_bps} bps per trade</span> : undefined} error={error} loading={!data}>
      {data && model && net && (
        <>
          <Hero months={model.monthly} names={names} models={data.models} compare={compare} onCompare={setCompare} />

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <Kpi icon={TrendingUp} label="Annual return" value={pct(net.ann_return, 1, true)} note="after costs" color={tone(net.ann_return)} />
            <Kpi icon={Gauge} label="Sharpe ratio" value={num(net.sharpe, 2)} note={`${net.months} months`} />
            <Kpi icon={ArrowDownRight} label="Max drawdown" value={pct(net.max_drawdown, 0)} note="peak to trough" color={CH.neg} />
            <Kpi icon={Repeat} label="Monthly turnover" value={num(net.avg_turnover, 2)} note="of the portfolio" />
            <Kpi icon={Sigma} label="Mean rank IC" value={num(model.mean_ic, 3, true)} note="test years" />
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <Models data={data.models} names={names} />
            <Years byYear={model.by_year} />
          </div>

          {data.by_index && data.by_index.length > 1 && (
            <section style={{ display: 'grid', gap: 10 }}>
              <h2 style={{ fontFamily: F.display, fontSize: 17, fontWeight: 650, color: C.text, margin: '6px 2px 0' }}>Inside each index</h2>
              <div className="grid gap-3 md:grid-cols-3">
                {data.by_index.map((b) => (
                  <Card key={b.index} style={{ padding: 16, display: 'grid', gap: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                      <span style={{ fontFamily: F.body, fontSize: 15, fontWeight: 650, color: C.text }}>{b.index}</span>
                      <span style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>since {monthLabel(b.from)}</span>
                    </div>
                    <div>
                      <div style={{ ...NUM, fontSize: 26, fontWeight: 650, letterSpacing: '-0.015em', color: tone(b.stats.long_short_net.ann_return) }}>{pct(b.stats.long_short_net.ann_return, 1, true)}</div>
                      <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>a year after costs · {pct(b.stats.long_short.ann_return, 1, true)} before</div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, borderTop: `1px solid ${C.rule}`, paddingTop: 10 }}>
                      <Mini label="Sharpe" value={num(b.stats.long_short_net.sharpe, 2)} />
                      <Mini label="Drawdown" value={pct(b.stats.long_short_net.max_drawdown, 0)} />
                      <Mini label="Rank IC" value={num(b.mean_ic.lgbm, 3, true)} />
                      <Mini label="Companies" value={String(b.companies)} />
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          )}

          <ChartCard title="Drawdown, after costs">
            <LineChart x={model.monthly.map((m) => m.month.slice(0, 7))} format={(v) => pct(v, 1)} zero area endLabels={false} height={200} series={[{ name: 'Below the previous peak', color: CH.neg, values: drawdown(model.monthly) }]} />
          </ChartCard>
        </>
      )}
    </Page>
  )
}

function Hero({ months, names, models, compare, onCompare }: { months: BacktestMonth[]; names: string[]; models: Record<string, { monthly: BacktestMonth[] }>; compare: Compare; onCompare: (c: Compare) => void }) {
  const values = growth(months, 'long_short_net')
  const end = values[values.length - 1] ?? START
  const total = end / START - 1
  const first = months[0]?.month ?? ''
  const series = [
    { name: 'Strategy', color: C.accent, values },
    ...(compare === 'bench' ? [{ name: 'S&P 500', color: CH.context, context: true, values: growth(months, 'bench') }] : []),
    ...(compare === 'models' ? names.filter((n) => n !== 'lgbm').map((n) => ({ name: NAMES[n] ?? n, color: CH.context, context: true, values: growth(models[n].monthly, 'long_short_net') })) : []),
  ]
  return (
    <Card style={{ padding: '18px 20px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>Growth of $10,000 · LightGBM ranker</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 4, flexWrap: 'wrap' }}>
            <span style={{ ...NUM, fontSize: 36, fontWeight: 650, letterSpacing: '-0.02em', color: C.text }}>{dollars(end)}</span>
            <span style={{ ...NUM, fontSize: 14, fontWeight: 650, color: tone(total), background: `color-mix(in srgb, ${tone(total)} 12%, transparent)`, borderRadius: 999, padding: '3px 10px' }}>
              {pct(total, 0, true)} since {monthLabel(first)}
            </span>
          </div>
          <div style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, marginTop: 4 }}>after trading costs</div>
        </div>
        <Segmented
          size="sm"
          value={compare}
          onChange={onCompare}
          options={[
            { value: 'none', label: 'Strategy' },
            { value: 'bench', label: 'vs S&P 500' },
            { value: 'models', label: 'vs baselines' },
          ]}
        />
      </div>
      <div style={{ marginTop: 10 }}>
        <LineChart x={months.map((m) => m.month.slice(0, 7))} series={series} format={dollars} axisFormat={(v) => `$${Math.round(v / 1000)}k`} area areaFloor height={300} endLabels={compare !== 'none'} />
      </div>
    </Card>
  )
}

function Kpi({ icon: Icon, label, value, note, color = C.text }: { icon: LucideIcon; label: string; value: string; note: string; color?: string }) {
  return (
    <Card style={{ padding: '14px 16px', display: 'grid', gap: 8 }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.body, fontSize: 12.5, color: C.muted }}>
        <span style={{ width: 26, height: 26, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: C.accentSoft, color: C.accent }}>
          <Icon size={14} />
        </span>
        {label}
      </span>
      <span style={{ ...NUM, fontSize: 24, fontWeight: 650, letterSpacing: '-0.015em', color }}>{value}</span>
      <span style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: -4 }}>{note}</span>
    </Card>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="truncate" style={{ fontFamily: F.body, fontSize: 11, color: C.muted }}>
        {label}
      </div>
      <div style={{ ...NUM, fontSize: 13.5, fontWeight: 600, color: C.text, marginTop: 2 }}>{value}</div>
    </div>
  )
}

/** Each model's annual return after costs as a bar from zero, best first, the ranker highlighted. */
function Models({ data, names }: { data: Record<string, { stats: { long_short_net: { ann_return: number; sharpe: number | null; max_drawdown: number } }; mean_ic: number }>; names: string[] }) {
  const rows = [...names].sort((a, b) => data[b].stats.long_short_net.ann_return - data[a].stats.long_short_net.ann_return)
  const max = Math.max(0.01, ...rows.map((n) => Math.abs(data[n].stats.long_short_net.ann_return)))
  return (
    <Card style={{ padding: '16px 18px' }}>
      <PanelTitle>Against the baselines</PanelTitle>
      <ul style={{ listStyle: 'none', margin: '12px 0 0', padding: 0, display: 'grid', gap: 12 }}>
        {rows.map((n) => {
          const s = data[n].stats.long_short_net
          const ours = n === 'lgbm'
          const half = (Math.abs(s.ann_return) / max) * 50
          return (
            <li key={n} style={{ display: 'grid', gap: 6, padding: ours ? '10px 12px' : '0 12px', borderRadius: 10, background: ours ? C.accentSoft : 'transparent', border: ours ? `1px solid ${C.edge}` : '1px solid transparent' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'baseline' }}>
                <span style={{ fontFamily: F.body, fontSize: 13.5, fontWeight: ours ? 650 : 500, color: C.text }}>{NAMES[n] ?? n}</span>
                <span style={{ ...NUM, fontSize: 14, fontWeight: 650, color: tone(s.ann_return) }}>{pct(s.ann_return, 1, true)}</span>
              </div>
              <span aria-hidden style={{ position: 'relative', height: 8, borderRadius: 4, background: `color-mix(in srgb, ${C.rule} 70%, transparent)` }}>
                <span style={{ position: 'absolute', left: 'calc(50% - 0.5px)', top: -3, bottom: -3, width: 1, background: C.muted, opacity: 0.6 }} />
                <span style={{ position: 'absolute', top: 0, bottom: 0, borderRadius: 4, width: `${half}%`, background: tone(s.ann_return), ...(s.ann_return >= 0 ? { left: '50%' } : { right: '50%' }) }} />
              </span>
              <span style={{ ...NUM, fontSize: 11.5, color: C.muted }}>
                Sharpe {num(s.sharpe, 2)} · drawdown {pct(s.max_drawdown, 0)} · IC {num(data[n].mean_ic, 3, true)}
              </span>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

/** One tile per year, tinted by the strategy's return after costs, with the S&P 500's year beneath. */
function Years({ byYear }: { byYear: { year: number; long_short_net: number; bench: number }[] }) {
  const max = Math.max(0.05, ...byYear.map((y) => Math.abs(y.long_short_net)))
  return (
    <Card style={{ padding: '16px 18px' }}>
      <PanelTitle>Year by year</PanelTitle>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" style={{ marginTop: 12 }}>
        {byYear.map((y) => {
          const v = y.long_short_net
          const strength = Math.round(12 + (Math.min(Math.abs(v), max) / max) * 50)
          return (
            <div key={y.year} title={`${y.year}: strategy ${pct(v, 1, true)}, S&P 500 ${pct(y.bench, 1, true)}`} style={{ borderRadius: 10, padding: '10px 10px 9px', background: `color-mix(in srgb, ${tone(v)} ${strength}%, var(--color-card))`, border: `1px solid color-mix(in srgb, ${tone(v)} 30%, transparent)` }}>
              <div style={{ ...NUM, fontSize: 12, fontWeight: 600, color: C.dim }}>{y.year}</div>
              <div style={{ ...NUM, fontSize: 17, fontWeight: 700, color: C.text, marginTop: 2 }}>{pct(v, 0, true)}</div>
              <div style={{ ...NUM, fontSize: 11, color: C.dim, marginTop: 1 }}>S&amp;P {pct(y.bench, 0, true)}</div>
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, fontFamily: F.body, fontSize: 12, color: C.muted }}>
        <Activity size={13} /> Strategy return after costs; S&amp;P 500 total return for the same year
      </div>
    </Card>
  )
}
