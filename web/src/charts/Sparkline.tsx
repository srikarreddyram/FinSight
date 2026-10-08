// A small line of recent closes with a soft area under it. Hovering marks the nearest day and reports it.
import { useId, useState } from 'react'
import { useWidth } from './util'

export function Sparkline({ points, color, height = 44, onHover }: { points: number[]; color: string; height?: number; onHover?: (i: number | null) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const gradient = `spark${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const n = points.length
  const set = (i: number | null) => {
    setHover(i)
    onHover?.(i)
  }
  if (n < 2) return <div ref={ref} style={{ height }} />
  const lo = Math.min(...points)
  const hi = Math.max(...points)
  const x = (i: number) => 1 + (i / (n - 1)) * Math.max(0, width - 2)
  const y = (v: number) => 3 + (1 - (v - lo) / (hi - lo || 1)) * (height - 6)
  const line = points.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  return (
    <div
      ref={ref}
      style={{ height, position: 'relative', cursor: 'crosshair', touchAction: 'pan-y' }}
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        set(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1)))))
      }}
      onPointerLeave={() => set(null)}
    >
      {width > 0 && (
        <svg width={width} height={height} aria-hidden style={{ display: 'block', overflow: 'visible' }}>
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.2} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={`${line}L${x(n - 1).toFixed(1)},${height}L${x(0).toFixed(1)},${height}Z`} fill={`url(#${gradient})`} />
          <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hover != null && (
            <>
              <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} stroke="var(--color-line)" strokeWidth={1} />
              <circle cx={x(hover)} cy={y(points[hover])} r={4} fill={color} stroke="var(--color-card)" strokeWidth={2} />
            </>
          )}
        </svg>
      )}
    </div>
  )
}
