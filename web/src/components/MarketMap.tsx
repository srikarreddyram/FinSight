// The market map: every company a tile sized by market cap, grouped by sector, coloured by its move over the
// window (green up, red down, gray flat), with the ticker and the signed change on tiles big enough to hold them.
import { useMemo, useState } from 'react'
import { Tooltip } from '../charts/core'
import { squarify, type Tile } from '../charts/treemap'
import { useWidth, type Tip } from '../charts/util'
import { Card, PanelTitle, Segmented, Skeleton } from '../design/primitives'
import { C, F, NUM } from '../design/tokens'
import { getMap } from '../news/api'
import type { MapTile, MoveWindow } from '../news/types'
import { useData } from '../pages/data'
import { cap, money, pct } from '../recs/format'
import { go } from '../shell/routes'

const INDEXES = ['S&P 500', 'S&P 400', 'S&P 600', 'All'] as const
type IndexChoice = (typeof INDEXES)[number]
// The change that gets the strongest colour, per window: a 3% day is as notable as a 15% month.
const FULL: Record<MoveWindow, number> = { '1d': 0.03, '1w': 0.075, '1m': 0.15 }
const HEADER = 18

function fill(change: number, window: MoveWindow): string {
  const t = Math.min(1, Math.abs(change) / FULL[window])
  if (t < 0.02) return 'var(--map-mid)'
  const end = change > 0 ? 'var(--map-pos)' : 'var(--map-neg)'
  return `color-mix(in oklab, ${end} ${Math.round(25 + 75 * t)}%, var(--map-mid))`
}

interface Placed {
  sector: string
  rect: Tile<string>
  tiles: Tile<MapTile>[]
}

function layout(tiles: MapTile[], width: number, height: number): Placed[] {
  const bySector = new Map<string, MapTile[]>()
  for (const t of tiles) bySector.set(t.sector, [...(bySector.get(t.sector) ?? []), t])
  const sectors = squarify(
    [...bySector.entries()].map(([s, list]) => ({ value: list.reduce((a, t) => a + t.cap, 0), data: s })),
    { x: 0, y: 0, w: width, h: height },
  )
  return sectors.map((rect) => {
    const head = rect.h > 60 && rect.w > 70 ? HEADER : 0
    const inner = { x: rect.x + 1, y: rect.y + head + 1, w: Math.max(0, rect.w - 2), h: Math.max(0, rect.h - head - 2) }
    return { sector: rect.data, rect, tiles: squarify((bySector.get(rect.data) ?? []).map((t) => ({ value: t.cap, data: t })), inner) }
  })
}

export function MarketMap({ window }: { window: MoveWindow }) {
  const [index, setIndex] = useState<IndexChoice>('S&P 500')
  const { data, error } = useData(() => getMap(window), window)
  const [ref, width] = useWidth<HTMLDivElement>()
  const [tip, setTip] = useState<Tip | null>(null)
  const height = Math.round(Math.min(720, Math.max(420, width * 0.56)))
  const tiles = useMemo(() => (data?.tiles ?? []).filter((t) => index === 'All' || t.index === index), [data, index])
  const placed = useMemo(() => (width > 0 ? layout(tiles, width, height) : []), [tiles, width, height])

  const show = (e: React.PointerEvent, t: MapTile) =>
    setTip({
      x: e.clientX,
      y: e.clientY,
      title: `${t.ticker} · ${t.name ?? ''}`,
      rows: [
        { color: fill(t.change, window), label: 'change', value: pct(t.change, 2, true) },
        ...(t.vs_sector != null ? [{ label: 'vs sector', value: pct(t.vs_sector, 1, true) }] : []),
        { label: 'price', value: money(t.price) },
        { label: `market cap · ${t.sector}`, value: cap(t.cap) },
      ],
    })

  return (
    <Card style={{ padding: '14px 18px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <PanelTitle>Market map</PanelTitle>
        <Segmented size="sm" value={index} onChange={setIndex} options={INDEXES.map((i) => ({ value: i, label: i }))} />
      </div>
      <div ref={ref} style={{ position: 'relative', minHeight: 420 }}>
        {error ? (
          <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>The map isn’t available right now ({error}).</div>
        ) : !data || data.status !== 'ready' ? (
          <Skeleton h={height} r={8} />
        ) : (
          width > 0 && (
            <svg width={width} height={height} role="img" aria-label={`Market map of ${tiles.length} companies, sized by market cap and coloured by their move`} onPointerLeave={() => setTip(null)} style={{ display: 'block', borderRadius: 8, overflow: 'hidden' }}>
              {placed.map((s) => (
                <g key={s.sector}>
                  <rect x={s.rect.x} y={s.rect.y} width={s.rect.w} height={s.rect.h} fill={C.surface} />
                  {s.rect.h > 60 && s.rect.w > 70 && (
                    <text x={s.rect.x + 6} y={s.rect.y + 13} style={{ fontFamily: F.body, fontSize: 11, fontWeight: 700, letterSpacing: '0.03em', textTransform: 'uppercase', fill: C.dim }}>
                      {s.sector.length * 7 > s.rect.w - 10 ? s.sector.slice(0, Math.max(3, Math.floor((s.rect.w - 16) / 7))) + '…' : s.sector}
                    </text>
                  )}
                  {s.tiles.map((t) => {
                    const big = t.w > 34 && t.h > 22
                    const size = Math.max(9, Math.min(22, Math.sqrt(t.w * t.h) / 5.5))
                    return (
                      <g key={t.data.ticker} onPointerMove={(e) => show(e, t.data)} onClick={() => go(`/company/${encodeURIComponent(t.data.ticker)}?w=${window}`)} style={{ cursor: 'pointer' }}>
                        <rect x={t.x} y={t.y} width={Math.max(0, t.w)} height={Math.max(0, t.h)} fill={fill(t.data.change, window)} stroke={C.surface} strokeWidth={1} />
                        {big && (
                          <text x={t.x + t.w / 2} y={t.y + t.h / 2} textAnchor="middle" style={{ fill: '#fff', pointerEvents: 'none' }}>
                            <tspan x={t.x + t.w / 2} dy={t.h > size * 2.6 ? -size * 0.25 : size * 0.35} style={{ ...NUM, fontSize: size, fontWeight: 700 }}>
                              {t.data.ticker}
                            </tspan>
                            {t.h > size * 2.6 && (
                              <tspan x={t.x + t.w / 2} dy={size * 1.05} style={{ ...NUM, fontSize: size * 0.72, fontWeight: 600, opacity: 0.95 }}>
                                {pct(t.data.change, 2, true)}
                              </tspan>
                            )}
                          </text>
                        )}
                      </g>
                    )
                  })}
                </g>
              ))}
            </svg>
          )
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>Size: market cap · Colour: change</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
          <span style={{ ...NUM, fontSize: 11.5, color: C.muted }}>{pct(-FULL[window], 1, true)}</span>
          {[-1, -0.66, -0.33, 0, 0.33, 0.66, 1].map((k) => (
            <span key={k} aria-hidden style={{ width: 22, height: 12, borderRadius: 3, background: fill(k * FULL[window], window) }} />
          ))}
          <span style={{ ...NUM, fontSize: 11.5, color: C.muted }}>{pct(FULL[window], 1, true)}</span>
        </span>
      </div>
      <Tooltip tip={tip} />
    </Card>
  )
}
