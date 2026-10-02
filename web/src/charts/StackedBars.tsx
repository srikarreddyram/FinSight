import { useState } from 'react'
import { C, F, NUM } from '../design/tokens'
import { Legend, Tooltip } from './core'
import type { Tip } from './util'

/** Horizontal part-to-whole bars: one row per category, segments separated by a 2px surface gap. */
export function StackedBars({
  rows,
  segments,
}: {
  rows: { label: string; counts: number[] }[]
  segments: { label: string; color: string }[]
}) {
  const [tip, setTip] = useState<Tip | null>(null)
  return (
    <div>
      <Legend shape="rect" items={segments} />
      <div style={{ display: 'grid', gap: 7 }}>
        {rows.map((r) => {
          const total = r.counts.reduce((a, b) => a + b, 0)
          return (
            <div key={r.label} style={{ display: 'grid', gridTemplateColumns: 'minmax(120px, 190px) 1fr 36px', alignItems: 'center', gap: 10 }}>
              <span style={{ fontFamily: F.body, fontSize: 12, color: C.dim, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
              <div style={{ display: 'flex', gap: 2, height: 14 }}>
                {r.counts.map((n, i) =>
                  n > 0 ? (
                    <span
                      key={i}
                      tabIndex={0}
                      aria-label={`${r.label}, ${segments[i].label}: ${n} of ${total}`}
                      onPointerMove={(e) =>
                        setTip({ x: e.clientX, y: e.clientY, title: r.label, rows: [{ color: segments[i].color, label: segments[i].label, value: `${n} of ${total}` }] })
                      }
                      onPointerLeave={() => setTip(null)}
                      onFocus={(e) => {
                        const b = e.currentTarget.getBoundingClientRect()
                        setTip({ x: b.left + b.width / 2, y: b.top, title: r.label, rows: [{ color: segments[i].color, label: segments[i].label, value: `${n} of ${total}` }] })
                      }}
                      onBlur={() => setTip(null)}
                      style={{ flex: n, background: segments[i].color, borderRadius: 2, minWidth: 3 }}
                    />
                  ) : null,
                )}
              </div>
              <span style={{ ...NUM, fontSize: 11, color: C.muted, textAlign: 'right' }}>{total}</span>
            </div>
          )
        })}
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}
