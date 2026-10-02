import { useState } from 'react'
import { C, CH } from '../design/tokens'
import { Tooltip } from './core'
import { AXIS_TEXT, ticks, useWidth } from './util'
import type { Tip } from './util'

/** Columns from a zero baseline (negative values hang below it). Each column is its own hover and focus target. */
export function ColumnChart({
  categories,
  values,
  color,
  format,
  height = 220,
  labels = true,
  name,
}: {
  categories: string[]
  values: (number | null)[]
  color: (v: number, i: number) => string
  format: (v: number) => string
  height?: number
  labels?: boolean
  /** What one column measures, for the tooltip. */
  name: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const [tip, setTip] = useState<Tip | null>(null)
  const m = { l: 48, r: 10, t: 18, b: 26 }
  const nums = values.filter((v): v is number => v != null)
  const lo = Math.min(0, ...nums)
  const hi = Math.max(0, ...nums)
  const pad = (hi - lo || 1) * 0.08
  const [d0, d1] = [lo < 0 ? lo - pad : 0, hi > 0 ? hi + pad : 0]
  const w = Math.max(0, width - m.l - m.r)
  const h = height - m.t - m.b
  const band = categories.length ? w / categories.length : 0
  const bar = Math.min(24, band * 0.62)
  const py = (v: number) => m.t + h - ((v - d0) / (d1 - d0 || 1)) * h
  const showLabels = labels && band >= 44

  const column = (i: number, v: number) => {
    const x = m.l + band * i + (band - bar) / 2
    const y0 = py(0)
    const y1 = py(v)
    const r = Math.min(4, Math.abs(y1 - y0), bar / 2)
    // Rounded at the data end only; square where it meets the baseline.
    return v >= 0
      ? `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + bar - r}Q${x + bar},${y1} ${x + bar},${y1 + r}V${y0}Z`
      : `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + bar - r}Q${x + bar},${y1} ${x + bar},${y1 - r}V${y0}Z`
  }
  const show = (i: number, x: number, y: number) => {
    const v = values[i]
    setHover(i)
    setTip(v == null ? null : { x, y, title: categories[i], rows: [{ label: name, value: format(v) }] })
  }
  const leave = () => {
    setHover(null)
    setTip(null)
  }

  return (
    <div ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} style={{ display: 'block' }} role="img" aria-label={`${name} by category`}>
          {ticks(d0, d1, 4).map((t) => (
            <g key={t}>
              <line x1={m.l} x2={m.l + w} y1={py(t)} y2={py(t)} stroke={t === 0 ? C.muted : CH.grid} strokeWidth={1} />
              <text x={m.l - 8} y={py(t)} textAnchor="end" dominantBaseline="central" style={AXIS_TEXT}>
                {format(t)}
              </text>
            </g>
          ))}
          {categories.map((c, i) => {
            const v = values[i]
            const cx = m.l + band * i + band / 2
            return (
              <g key={c}>
                {v != null && (
                  <>
                    <path d={column(i, v)} fill={color(v, i)} opacity={hover == null || hover === i ? 1 : 0.55} />
                    {showLabels && (
                      <text x={cx} y={v >= 0 ? py(v) - 6 : py(v) + 12} textAnchor="middle" style={{ ...AXIS_TEXT, fill: C.dim }}>
                        {format(v)}
                      </text>
                    )}
                  </>
                )}
                <text x={cx} y={height - 8} textAnchor="middle" style={AXIS_TEXT}>
                  {c}
                </text>
                {/* The hit target is the whole band, not just the painted column. */}
                <rect
                  x={m.l + band * i}
                  y={m.t}
                  width={band}
                  height={h}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={v == null ? `${c}: no value` : `${c}: ${format(v)}`}
                  onPointerMove={(e) => show(i, e.clientX, e.clientY)}
                  onPointerLeave={leave}
                  onFocus={(e) => {
                    const r = e.currentTarget.getBoundingClientRect()
                    show(i, r.left + r.width / 2, r.top + 20)
                  }}
                  onBlur={leave}
                  style={{ outlineOffset: -2 }}
                />
              </g>
            )
          })}
        </svg>
      )}
      <Tooltip tip={tip} />
    </div>
  )
}
