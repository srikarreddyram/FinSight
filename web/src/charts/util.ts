// Chart helpers that are not components: sizing, ticks, axis text style, the tooltip's shape.
import { useCallback, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { C, NUM } from '../design/tokens'

/** Width of a container: measured as soon as it mounts, then tracked as it resizes. A callback ref, so the
 *  first measurement doesn't wait for the ResizeObserver's first report (and a chart never paints empty). */
export function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [width, setWidth] = useState(0)
  const observer = useRef<ResizeObserver | null>(null)
  const ref = useCallback((el: T | null) => {
    observer.current?.disconnect()
    observer.current = null
    if (!el) return
    setWidth(Math.floor(el.getBoundingClientRect().width))
    observer.current = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    observer.current.observe(el)
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
