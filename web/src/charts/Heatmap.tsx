import { useState } from 'react'
import { C, CH, F, NUM } from '../design/tokens'
import { Tooltip } from './core'
import type { Tip } from './util'

/** A grid of values around zero: two opposite hues that fade to the surface's neutral at the midpoint. */
export function Heatmap({
  rows,
  cols,
  value,
  max,
  format,
  onRow,
}: {
  rows: { key: string; label: string }[]
  cols: string[]
  value: (rowKey: string, col: string) => number | null
  /** The value that gets full colour; larger values are capped. */
  max: number
  format: (v: number) => string
  onRow?: (key: string) => void
}) {
  const [tip, setTip] = useState<Tip | null>(null)
  const fill = (v: number | null) =>
    v == null ? 'transparent' : `color-mix(in srgb, ${v >= 0 ? CH.pos : CH.neg} ${Math.round(Math.min(1, Math.abs(v) / max) * 100)}%, ${C.rule})`
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, fontFamily: F.mono, fontSize: 10, color: C.muted }}>
        <span>{format(-max)}</span>
        <span
          aria-hidden
          style={{ width: 150, height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${CH.neg}, ${C.rule} 50%, ${CH.pos})` }}
        />
        <span>{format(max)}</span>
        <span style={{ marginLeft: 6 }}>blank = not enough data</span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: `minmax(170px, 240px) repeat(${cols.length}, minmax(26px, 1fr))`, gap: 2, minWidth: 170 + cols.length * 28 }}>
          <span />
          {cols.map((c) => (
            <span key={c} style={{ ...NUM, fontSize: 9.5, color: C.muted, textAlign: 'center', paddingBottom: 3 }}>
              {c.slice(2)}
            </span>
          ))}
          {rows.map((r) => (
            <div key={r.key} style={{ display: 'contents' }}>
              <button
                type="button"
                onClick={onRow ? () => onRow(r.key) : undefined}
                style={{ all: 'unset', fontFamily: F.body, fontSize: 11.5, color: C.dim, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: '20px' }}
                title={r.label}
              >
                {r.label}
              </button>
              {cols.map((c) => {
                const v = value(r.key, c)
                return (
                  <span
                    key={c}
                    tabIndex={v == null ? -1 : 0}
                    aria-label={v == null ? undefined : `${r.label}, ${c}: ${format(v)}`}
                    onPointerMove={(e) => v != null && setTip({ x: e.clientX, y: e.clientY, title: `${r.label} · ${c}`, rows: [{ label: 'rank IC', value: format(v) }] })}
                    onPointerLeave={() => setTip(null)}
                    onFocus={(e) => {
                      const b = e.currentTarget.getBoundingClientRect()
                      if (v != null) setTip({ x: b.left + b.width / 2, y: b.top, title: `${r.label} · ${c}`, rows: [{ label: 'rank IC', value: format(v) }] })
                    }}
                    onBlur={() => setTip(null)}
                    style={{ height: 20, borderRadius: 2, background: fill(v), outlineOffset: 1 }}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}
