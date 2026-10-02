// Shared chart components: the tooltip, the legend and the card frame with its table view.
import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Card, SectionLabel, Segmented } from '../design/primitives'
import { C, F, NUM } from '../design/tokens'
import type { Tip } from './util'

/** One tooltip for every series at the hovered position: values lead, labels follow. Never the only way to read a value. */
export function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null
  const flip = tip.x > window.innerWidth - 260
  return (
    <div
      role="status"
      style={{
        position: 'fixed',
        left: flip ? undefined : tip.x + 14,
        right: flip ? window.innerWidth - tip.x + 14 : undefined,
        top: Math.max(8, tip.y - 12),
        zIndex: 60,
        pointerEvents: 'none',
        background: C.raised,
        border: `1px solid ${C.rule}`,
        borderRadius: 6,
        padding: '8px 10px',
        boxShadow: '0 6px 24px rgb(0 0 0 / 0.14)',
        minWidth: 150,
        maxWidth: 280,
      }}
    >
      <div style={{ fontFamily: F.mono, fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: C.muted, marginBottom: 5 }}>
        {tip.title}
      </div>
      {tip.rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.7 }}>
          {r.color && <span aria-hidden style={{ width: 12, height: 2, background: r.color, borderRadius: 1, flex: 'none' }} />}
          <span style={{ ...NUM, fontSize: 12.5, fontWeight: 600, color: C.text }}>{r.value}</span>
          <span style={{ fontFamily: F.body, fontSize: 11.5, color: C.muted }}>{r.label}</span>
        </div>
      ))}
    </div>
  )
}

export function Legend({ items, shape = 'line' }: { items: { color: string; label: string }[]; shape?: 'line' | 'rect' }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px', marginBottom: 8 }}>
      {items.map((it) => (
        <span key={it.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 11.5, color: C.dim }}>
          <span
            aria-hidden
            style={shape === 'line' ? { width: 14, height: 2, background: it.color, borderRadius: 1 } : { width: 10, height: 10, background: it.color, borderRadius: 2 }}
          />
          {it.label}
        </span>
      ))}
    </div>
  )
}

/** A chart in a card: what it shows, a note on how to read it, and a table view of the same numbers. */
export function ChartCard({
  title,
  note,
  children,
  table,
  style,
}: {
  title: string
  note?: ReactNode
  children: ReactNode
  table?: ReactNode
  style?: CSSProperties
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  return (
    <Card style={{ padding: '16px 18px', minWidth: 0, ...style }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <div style={{ minWidth: 0 }}>
          <SectionLabel style={{ letterSpacing: '0.24em' }}>{title}</SectionLabel>
          {note && <div style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, marginTop: 6, lineHeight: 1.55, maxWidth: 720 }}>{note}</div>}
        </div>
        {table && (
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: 'chart', label: 'Chart' },
              { value: 'table', label: 'Table' },
            ]}
          />
        )}
      </div>
      {view === 'table' && table ? <div style={{ overflowX: 'auto', maxHeight: 420, overflowY: 'auto' }}>{table}</div> : children}
    </Card>
  )
}
