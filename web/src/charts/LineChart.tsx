import { useState } from 'react'
import { C, CH } from '../design/tokens'
import { Legend, Tooltip } from './core'
import { AXIS_TEXT, ticks, useWidth } from './util'
import type { Tip } from './util'

export interface LineSeries {
  name: string
  color: string
  values: (number | null)[]
  /** Context series are drawn thinner and are not labelled at their end. */
  context?: boolean
}

/** Lines over time on one shared axis. A crosshair snaps to the nearest date and reads out every series. */
export function LineChart({
  x,
  series,
  format,
  xLabel = (s) => s.slice(0, 4),
  height = 260,
  zero = false,
  area = false,
  domain,
  step = false,
  endLabels = true,
  tickValues,
  axisFormat,
}: {
  x: string[]
  series: LineSeries[]
  format: (v: number) => string
  xLabel?: (s: string) => string
  height?: number
  zero?: boolean
  area?: boolean
  domain?: [number, number]
  step?: boolean
  endLabels?: boolean
  tickValues?: number[]
  /** Shorter labels for the axis when the tooltip's format is too long to fit beside it. */
  axisFormat?: (v: number) => string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const [tip, setTip] = useState<Tip | null>(null)
  const labelled = endLabels ? series.filter((s) => !s.context) : []
  const m = { l: 48, r: labelled.length ? 92 : 14, t: 10, b: 26 }
  const all = series.flatMap((s) => s.values.filter((v): v is number => v != null))
  let lo = domain ? domain[0] : Math.min(...all, zero ? 0 : Infinity)
  let hi = domain ? domain[1] : Math.max(...all, zero ? 0 : -Infinity)
  if (!domain) {
    const pad = (hi - lo || 1) * 0.06
    lo -= pad
    hi += pad
  }
  const w = Math.max(0, width - m.l - m.r)
  const h = height - m.t - m.b
  const n = x.length
  const px = (i: number) => m.l + (n > 1 ? (i / (n - 1)) * w : w / 2)
  const py = (v: number) => m.t + h - ((v - lo) / (hi - lo || 1)) * h
  const yt = tickValues ?? ticks(lo, hi, 4)
  // One tick where each new label starts (each January for monthly data), thinned to fit the width.
  const starts = x.map((_, i) => i).filter((i) => i === 0 || xLabel(x[i]) !== xLabel(x[i - 1]))
  const keep = Math.max(1, Math.ceil(starts.length / Math.max(2, Math.floor(w / 56))))
  const xTicks = new Set(starts.filter((_, k) => k % keep === 0))

  const path = (vals: (number | null)[]) => {
    let d = ''
    let pen = false
    vals.forEach((v, i) => {
      if (v == null) {
        pen = false
        return
      }
      if (!pen) d += `M${px(i).toFixed(1)},${py(v).toFixed(1)}`
      else if (step) d += `H${px(i).toFixed(1)}V${py(v).toFixed(1)}`
      else d += `L${px(i).toFixed(1)},${py(v).toFixed(1)}`
      pen = true
    })
    return d
  }

  const show = (i: number, clientX: number, clientY: number) => {
    setHover(i)
    setTip({
      x: clientX,
      y: clientY,
      title: x[i],
      rows: series.filter((s) => s.values[i] != null).map((s) => ({ color: s.color, label: s.name, value: format(s.values[i] as number) })),
    })
  }
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const i = Math.round(((e.clientX - rect.left - m.l) / (w || 1)) * (n - 1))
    show(Math.max(0, Math.min(n - 1, i)), e.clientX, e.clientY)
  }
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const i = Math.max(0, Math.min(n - 1, (hover ?? n - 1) + (e.key === 'ArrowRight' ? 1 : -1)))
    const rect = e.currentTarget.getBoundingClientRect()
    show(i, rect.left + px(i), rect.top + m.t + 20)
  }
  const leave = () => {
    setHover(null)
    setTip(null)
  }

  return (
    <div>
      {series.length > 1 && <Legend items={series.map((s) => ({ color: s.color, label: s.name }))} />}
      <div ref={ref} tabIndex={0} onKeyDown={onKey} onBlur={leave} aria-label="Line chart. Use the left and right arrow keys to read values." style={{ outlineOffset: 4 }}>
        {width > 0 && n > 0 && (
          <svg width={width} height={height} onPointerMove={onMove} onPointerLeave={leave} style={{ display: 'block', touchAction: 'pan-y' }}>
            {yt.map((t) => (
              <g key={t}>
                <line x1={m.l} x2={m.l + w} y1={py(t)} y2={py(t)} stroke={t === 0 && zero ? C.muted : CH.grid} strokeWidth={1} />
                <text x={m.l - 8} y={py(t)} textAnchor="end" dominantBaseline="central" style={AXIS_TEXT}>
                  {(axisFormat ?? format)(t)}
                </text>
              </g>
            ))}
            {x.map((label, i) =>
              xTicks.has(i) ? (
                <text key={i} x={px(i)} y={height - 8} textAnchor={i === 0 ? 'start' : 'middle'} style={AXIS_TEXT}>
                  {xLabel(label)}
                </text>
              ) : null,
            )}
            {area && series[0] && (
              <path d={`${path(series[0].values)}V${py(Math.max(lo, Math.min(hi, 0)))}H${px(0)}Z`} fill={series[0].color} opacity={0.1} />
            )}
            {[...series].reverse().map((s) => (
              <path key={s.name} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={s.context ? 1.25 : 2} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {labelled.map((s) => {
              const last = s.values.findLastIndex((v) => v != null)
              if (last < 0) return null
              const v = s.values[last] as number
              return (
                <g key={s.name}>
                  <circle cx={px(last)} cy={py(v)} r={4} fill={s.color} stroke={C.surface} strokeWidth={2} />
                  <text x={px(last) + 9} y={py(v)} dominantBaseline="central" style={{ ...AXIS_TEXT, fontSize: 11, fill: C.dim }}>
                    {format(v)}
                  </text>
                </g>
              )
            })}
            {hover != null && (
              <g pointerEvents="none">
                <line x1={px(hover)} x2={px(hover)} y1={m.t} y2={m.t + h} stroke={C.muted} strokeWidth={1} />
                {series.map((s) =>
                  s.values[hover] != null ? (
                    <circle key={s.name} cx={px(hover)} cy={py(s.values[hover] as number)} r={4} fill={s.color} stroke={C.surface} strokeWidth={2} />
                  ) : null,
                )}
              </g>
            )}
          </svg>
        )}
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}
