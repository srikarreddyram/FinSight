// The stock's price over 1M / 6M / 1Y / 5Y: green when the range ended up, red when down, earnings days marked.
import { useState } from 'react'
import { LineChart } from '../charts/LineChart'
import { DEMO } from '../demo'
import { Card, Segmented, Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getHistory } from '../news/api'
import type { PriceRange } from '../news/types'
import { useData } from '../pages/data'
import { money, pct } from '../recs/format'

const RANGES: { value: PriceRange; label: string }[] = [
  { value: '1m', label: '1M' },
  { value: '6m', label: '6M' },
  { value: '1y', label: '1Y' },
  ...(DEMO ? [] : [{ value: '5y' as const, label: '5Y' }]), // the demo snapshot keeps one year
]
const SINCE: Record<PriceRange, string> = { '1m': 'past month', '6m': 'past 6 months', '1y': 'past year', '5y': 'past 5 years' }

export function PriceChart({ ticker }: { ticker: string }) {
  const [range, setRange] = useState<PriceRange>('1y')
  const { data, error } = useData(() => getHistory(ticker, range), `${ticker}:${range}`)
  const x = data?.points.map((p) => p.day) ?? []
  const index = new Map(x.map((d, i) => [d, i]))
  // An earnings filing on a non-trading day marks the next trading day.
  const markers = (data?.earnings ?? [])
    .map((d) => index.get(d) ?? x.findIndex((day) => day > d))
    .filter((i) => i >= 0)
    .map((i) => ({ index: i, label: 'Earnings reported (8-K)', short: 'E' }))
  const up = (data?.change ?? 0) >= 0
  return (
    <Card style={{ padding: '16px 18px 14px' }}>
      {error ? (
        <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>Price history isn’t available right now ({error}).</div>
      ) : !data ? (
        <Skeleton h={250} r={8} />
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
            <span style={{ ...NUM, fontSize: 15, fontWeight: 600, color: up ? CH.pos : CH.neg }}>{pct(data.change, 2, true)}</span>
            <span style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>{SINCE[range]}</span>
          </div>
          <LineChart
            x={x}
            series={[{ name: 'Close', color: up ? CH.pos : CH.neg, values: data.points.map((p) => p.close) }]}
            format={(v) => money(v)}
            axisFormat={(v) => `$${v >= 1000 ? v.toFixed(0) : v.toFixed(v < 10 ? 2 : 0)}`}
            xLabel={(d) => (range === '1m' ? d.slice(5, 10) : range === '5y' ? d.slice(0, 4) : new Date(`${d}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' }))}
            height={250}
            area
            areaFloor
            endLabels={false}
            markers={markers}
          />
        </>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
        <Segmented size="sm" value={range} onChange={setRange} options={RANGES} />
        {markers.length > 0 && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 12, color: C.muted }}>
            <span style={{ width: 14, height: 14, borderRadius: 999, border: `1px solid ${C.muted}`, fontSize: 8.5, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: C.dim }}>E</span>
            Earnings
          </span>
        )}
      </div>
    </Card>
  )
}
