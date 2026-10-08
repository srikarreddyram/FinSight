// The page backdrop: a faint candlestick chart with its moving average and gridlines behind the top of every
// page, fading out downwards. The prices are a fixed-seed random walk, so it looks the same on every load.
import { memo } from 'react'

const W = 1440
const H = 560
const N = 72 // candles across

function rng(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

interface Candle {
  open: number
  close: number
  high: number
  low: number
}

const candles: Candle[] = (() => {
  const r = rng(20261006)
  const out: Candle[] = []
  let price = 100
  for (let i = 0; i < N; i++) {
    const open = price
    const close = open * (1 + (r() - 0.46) * 0.045) // a gentle upward drift
    const high = Math.max(open, close) * (1 + r() * 0.015)
    const low = Math.min(open, close) * (1 - r() * 0.015)
    out.push({ open, close, high, low })
    price = close
  }
  return out
})()

const lo = Math.min(...candles.map((c) => c.low))
const hi = Math.max(...candles.map((c) => c.high))
const step = W / N
const x = (i: number) => step * (i + 0.5)
const y = (v: number) => H * 0.92 - ((v - lo) / (hi - lo)) * H * 0.62 // the chart rises from the bottom right
const ma = candles.map((_, i) => {
  const w = candles.slice(Math.max(0, i - 7), i + 1)
  return w.reduce((a, c) => a + c.close, 0) / w.length
})
const line = ma.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')

export const Backdrop = memo(function Backdrop() {
  return (
    <div aria-hidden className="backdrop">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMax slice" width="100%" height="100%">
        <defs>
          <linearGradient id="backdrop-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.16} />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        {Array.from({ length: Math.floor(H / 56) }, (_, i) => (
          <line key={i} x1={0} x2={W} y1={56 * (i + 1)} y2={56 * (i + 1)} stroke="var(--bg-grid)" strokeWidth={1} />
        ))}
        <path d={`${line}L${x(N - 1)},${H}L${x(0)},${H}Z`} fill="url(#backdrop-area)" />
        <g style={{ opacity: 'var(--bg-candles)' }}>
          {candles.map((c, i) => {
            const color = c.close >= c.open ? 'var(--chart-pos)' : 'var(--chart-neg)'
            const top = y(Math.max(c.open, c.close))
            return (
              <g key={i}>
                <line x1={x(i)} x2={x(i)} y1={y(c.high)} y2={y(c.low)} stroke={color} strokeWidth={1.5} />
                <rect x={x(i) - step * 0.3} y={top} width={step * 0.6} height={Math.max(2, y(Math.min(c.open, c.close)) - top)} rx={1.5} fill={color} />
              </g>
            )
          })}
        </g>
        <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth={2} strokeLinejoin="round" style={{ opacity: 'var(--bg-line)' }} />
      </svg>
    </div>
  )
})
