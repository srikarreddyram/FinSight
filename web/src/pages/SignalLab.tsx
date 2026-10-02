import { useMemo, useState } from 'react'
import { ChartCard } from '../charts/core'
import { Heatmap } from '../charts/Heatmap'
import { Card, Segmented } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getSignals } from '../recs/api'
import { num, pct } from '../recs/format'
import type { SignalRow } from '../recs/types'
import { useData } from './data'
import { Page } from './shared'

export function SignalLab() {
  const { data, error } = useData(getSignals)
  const [scope, setScope] = useState<'raw' | 'sector'>('raw')
  const [family, setFamily] = useState('')
  const families = useMemo(() => [...new Set((data ?? []).map((s) => s.family))].sort(), [data])
  const rows = useMemo(() => {
    const ic = (s: SignalRow) => (scope === 'raw' ? s.ic_raw : s.ic_sector) ?? 0
    return (data ?? []).filter((s) => !family || s.family === family).sort((a, b) => Math.abs(ic(b)) - Math.abs(ic(a)))
  }, [data, family, scope])
  const ic = (s: SignalRow) => (scope === 'raw' ? s.ic_raw : s.ic_sector) ?? 0
  const years = useMemo(() => [...new Set((data ?? []).flatMap((s) => s.by_year.map((y) => String(y.year))))].sort(), [data])
  const scale = Math.max(0.01, ...rows.map((s) => Math.abs(ic(s))))

  return (
    <Page
      title="Signal Lab"
      lead="How well each signal, on its own, ranked stocks by their next 12 months of return relative to the S&P 500. Rank IC is the correlation between the signal’s ranking and the outcome’s: 0 is no skill, and 0.05 sustained over years is a strong single signal."
      error={error}
      loading={!data}
    >
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <select
          value={family}
          onChange={(e) => setFamily(e.target.value)}
          aria-label="Signal family"
          style={{ fontFamily: F.mono, fontSize: 11, padding: '7px 10px', borderRadius: 6, background: C.surface, color: C.text, border: `1px solid ${C.rule}` }}
        >
          <option value="">All families</option>
          {families.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
        <Segmented
          value={scope}
          onChange={setScope}
          options={[
            { value: 'raw', label: 'Across the market', title: 'Each stock ranked against the whole universe' },
            { value: 'sector', label: 'Within sector', title: 'Each stock ranked against its sector peers only' },
          ]}
        />
      </div>

      <Card style={{ overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="dash-table">
            <thead>
              <tr>
                <th className="left">Signal</th>
                <th className="left">Family</th>
                <th className="left" style={{ minWidth: 240 }}>
                  Mean rank IC, 2011–2025
                </th>
                <th title="t-statistic on yearly mean ICs: monthly ICs of a 12-month outcome overlap, so yearly means are the honest sample">t-stat</th>
                <th>Years positive</th>
                <th title="Average 12-month excess return of the top fifth minus the bottom fifth">Top − bottom fifth</th>
                <th title="Share of stock-months where the signal can be computed">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const v = ic(s)
                const half = (Math.abs(v) / scale) * 50
                return (
                  <tr key={s.signal}>
                    <td className="left" style={{ fontFamily: F.body, color: C.text }}>
                      {s.label}
                    </td>
                    <td className="left" style={{ fontFamily: F.body, color: C.muted }}>
                      {s.family}
                    </td>
                    <td className="left">
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
                        <span aria-hidden style={{ position: 'relative', width: 170, height: 10, display: 'inline-block' }}>
                          <span style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: C.muted }} />
                          <span
                            style={{
                              position: 'absolute',
                              top: 2,
                              height: 6,
                              left: v >= 0 ? '50%' : `${50 - half}%`,
                              width: `${half}%`,
                              background: v >= 0 ? CH.pos : CH.neg,
                              borderRadius: v >= 0 ? '0 3px 3px 0' : '3px 0 0 3px',
                            }}
                          />
                        </span>
                        <span style={{ ...NUM, fontWeight: 600, color: C.text }}>{num(v, 3, true)}</span>
                      </span>
                    </td>
                    <td>{num(scope === 'raw' ? s.t_raw : s.t_sector, 1, true)}</td>
                    <td>{(scope === 'raw' ? s.years_pos_raw : s.years_pos_sector) ?? '–'}</td>
                    <td>{pct(scope === 'raw' ? s.spread_raw : s.spread_sector, 1, true)}</td>
                    <td>{pct(s.coverage, 0)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <ChartCard
        title="Rank IC by year"
        note="One row per signal, one column per year. A signal worth trusting is the same colour most years, not strong on average because of one."
        table={
          <table className="dash-table">
            <thead>
              <tr>
                <th className="left">Signal</th>
                {years.map((y) => (
                  <th key={y}>{y}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.signal}>
                  <td className="left">{s.label}</td>
                  {years.map((y) => {
                    const cell = s.by_year.find((b) => String(b.year) === y)
                    return <td key={y}>{num(scope === 'raw' ? cell?.ic : cell?.ic_sector, 2, true)}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        }
      >
        <Heatmap
          rows={rows.map((s) => ({ key: s.signal, label: s.label }))}
          cols={years}
          max={0.15}
          format={(v) => num(v, 2, true)}
          value={(key, year) => {
            const cell = rows.find((s) => s.signal === key)?.by_year.find((b) => String(b.year) === year)
            return (scope === 'raw' ? cell?.ic : cell?.ic_sector) ?? null
          }}
        />
      </ChartCard>
    </Page>
  )
}
