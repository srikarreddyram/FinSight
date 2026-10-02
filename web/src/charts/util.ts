// Chart helpers that are not components: sizing, ticks, axis text style, the tooltip's shape.
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { C, NUM } from '../design/tokens'

/** Width of a container, tracked as it resizes. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

/** Round tick values covering [min, max]. */
export function ticks(min: number, max: number, count = 4): number[] {
  if (!(max > min)) return [min]
  const raw = (max - min) / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v)
  return out
}

export interface Tip {
  x: number
  y: number
  title: string
  rows: { color?: string; label: string; value: string }[]
}

export const AXIS_TEXT: CSSProperties = { ...NUM, fontSize: 10, fill: C.muted }
