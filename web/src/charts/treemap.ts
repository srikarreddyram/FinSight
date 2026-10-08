// Squarified treemap layout (Bruls, Huizing and van Wijk, 2000): rectangles with areas proportional to values,
// laid out row by row so each row's worst aspect ratio stays as close to square as it can.

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface Tile<T> extends Rect {
  data: T
}

interface Item<T> {
  area: number
  data: T
}

/** The worst (largest) aspect ratio in a row of areas laid along a side of this length. */
function worst(areas: number[], side: number): number {
  if (!areas.length) return Infinity
  const sum = areas.reduce((a, b) => a + b, 0)
  const max = Math.max(...areas)
  const min = Math.min(...areas)
  const s2 = side * side
  return Math.max((s2 * max) / (sum * sum), (sum * sum) / (s2 * min))
}

/** Lays a finished row along the shorter side of r, appends its tiles, and returns the space left. */
function place<T>(row: Item<T>[], r: Rect, out: Tile<T>[]): Rect {
  const sum = row.reduce((a, b) => a + b.area, 0)
  if (r.w >= r.h) {
    const w = r.h > 0 ? sum / r.h : 0
    let y = r.y
    for (const it of row) {
      const h = w > 0 ? it.area / w : 0
      out.push({ data: it.data, x: r.x, y, w, h })
      y += h
    }
    return { x: r.x + w, y: r.y, w: r.w - w, h: r.h }
  }
  const h = r.w > 0 ? sum / r.w : 0
  let x = r.x
  for (const it of row) {
    const w = h > 0 ? it.area / h : 0
    out.push({ data: it.data, x, y: r.y, w, h })
    x += w
  }
  return { x: r.x, y: r.y + h, w: r.w, h: r.h - h }
}

export function squarify<T>(nodes: { value: number; data: T }[], rect: Rect): Tile<T>[] {
  const positive = nodes.filter((n) => n.value > 0)
  const total = positive.reduce((a, n) => a + n.value, 0)
  if (!total || rect.w <= 0 || rect.h <= 0) return []
  const scale = (rect.w * rect.h) / total
  const items = positive.map((n) => ({ area: n.value * scale, data: n.data })).sort((a, b) => b.area - a.area)
  const out: Tile<T>[] = []
  let r = { ...rect }
  let row: Item<T>[] = []
  let i = 0
  while (i < items.length) {
    const side = Math.min(r.w, r.h)
    const areas = row.map((x) => x.area)
    if (!row.length || worst([...areas, items[i].area], side) <= worst(areas, side)) {
      row.push(items[i])
      i++
    } else {
      r = place(row, r, out)
      row = []
    }
  }
  if (row.length) place(row, r, out)
  return out
}
