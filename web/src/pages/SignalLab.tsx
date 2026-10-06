import { useMemo, useState } from 'react'
import { ChartCard } from '../charts/core'
import { Heatmap } from '../charts/Heatmap'
import { Card, Segmented } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getSignals } from '../recs/api'
import { num, pct } from '../recs/format'
import type { SignalRow, SignalStats } from '../recs/types'
import { useData } from './data'
import { Page } from './shared'

export function SignalLab() {
  const { data, error } = useData(getSignals)
  const [scope, setScope] = useState<'raw' | 'sector'>('raw')
  const [family, setFamily] = useState('')
  const [index, setIndex] = useState('')
  const families = useMemo(() => [...new Set((data ?? []).map((s) => s.family))].sort(), [data])
  const indexes = useMemo(() => (data?.[0]?.by_index ?? []).map((b) => b.index), [data])
  // The table's numbers: the whole universe, or the same study inside one index.
  const stats = (s: SignalRow): SignalStats | undefined => (index ? s.by_index?.find((b) => b.index === index) : s)
  const ic = (s: SignalRow) => (scope === 'raw' ? stats(s)?.ic_raw : stats(s)?.ic_sector) ?? 0
  const rows = (data ?? []).filter((s) => !family || s.family === family).sort((a, b) => Math.abs(ic(b)) - Math.abs(ic(a)))
  const years = useMemo(() => [...new Set((data ?? []).flatMap((s) => s.by_year.map((y) => String(y.year))))].sort(), [data])
  const scale = Math.max(0.01, ...rows.map((s) => Math.abs(ic(s))))

  return (
    <Page
      title="Signal Lab"
      error={error}
      loading={!data}
    >
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={family} onChange={(e) => setFamily(e.target.value)} aria-label="Signal family" className="control">
          <option value="">All families</option>
          {families.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
        {indexes.length > 1 && (
          <Segmented
            value={index}
            onChange={setIndex}
            options={[{ value: '', label: 'All indexes', title: 'Every stock-month in the universe' }, ...indexes.map((i) => ({ value: i, label: i, title: `Only months a company was in the ${i}` }))]}
          />
        )}
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
                  {index ? `Mean rank IC, ${index} months only` : 'Mean rank IC, 2011–2025'}
                </th>
                <th>t-stat</th>
                <th>Years positive</th>
                <th>Top − bottom fifth</th>
                <th>Coverage</th>
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
                    <td>{num(scope === 'raw' ? stats(s)?.t_raw : stats(s)?.t_sector, 1, true)}</td>
                    <td>{(scope === 'raw' ? stats(s)?.years_pos_raw : stats(s)?.years_pos_sector) ?? '–'}</td>
                    <td>{pct(scope === 'raw' ? stats(s)?.spread_raw : stats(s)?.spread_sector, 1, true)}</td>
                    <td>{pct(stats(s)?.coverage, 0)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <ChartCard
        title="Rank IC by year"
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
