// "Financials" on a company page: four fiscal years of the main lines. Every figure links to the filing it was
// reported in (hover for the form, period and filing date); ratios show how they were computed.
import { ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { Card, Skeleton } from '../design/primitives'
import { C, F, NUM } from '../design/tokens'
import { useData } from '../pages/data'
import { pct } from '../recs/format'
import { getFinancials } from '../research/api'
import type { SourcedValue } from '../research/types'

const money = (v: number) => {
  const a = Math.abs(v)
  const s = a >= 1e12 ? `$${(a / 1e12).toFixed(2)}T` : a >= 1e9 ? `$${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `$${(a / 1e6).toFixed(0)}M` : `$${a.toLocaleString()}`
  return v < 0 ? `−${s}` : s
}
const fy = (iso: string) => `FY${iso.slice(0, 4)}`
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

export function Financials({ ticker }: { ticker: string }) {
  const { data, error } = useData(() => getFinancials(ticker), ticker)
  const [tip, setTip] = useState<{ x: number; y: number; v: SourcedValue; label: string; year: string } | null>(null)
  if (error) return <Card style={{ padding: 18, fontFamily: F.body, fontSize: 13.5, color: C.muted }}>{error}</Card>
  if (!data) return <Skeleton h={360} r={14} />
  const cols = `minmax(150px, 1.4fr) repeat(${data.years.length}, minmax(84px, 1fr)) 72px`
  const head = (
    <div style={{ display: 'grid', gridTemplateColumns: cols, gap: 8, padding: '0 16px 8px', borderBottom: `1px solid ${C.rule}` }}>
      <span style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>Fiscal year ending</span>
      {data.years.map((y) => (
        <span key={y} style={{ ...NUM, fontSize: 12, fontWeight: 600, color: C.dim, textAlign: 'right' }} title={`Year to ${day(y)}`}>
          {fy(y)}
        </span>
      ))}
      <span style={{ fontFamily: F.body, fontSize: 12, color: C.muted, textAlign: 'right' }}>Trend</span>
    </div>
  )
  return (
    <div style={{ display: 'grid', gap: 14 }} onPointerLeave={() => setTip(null)}>
      <Card style={{ padding: '14px 0 6px', overflowX: 'auto' }}>
        <div style={{ minWidth: 640 }}>
          {head}
          {data.rows.map((r) => (
            <div key={r.item} style={{ display: 'grid', gridTemplateColumns: cols, gap: 8, alignItems: 'center', padding: '9px 16px', borderBottom: `1px solid ${C.rule}` }}>
              <span style={{ fontFamily: F.body, fontSize: 13.5, fontWeight: 600, color: C.text }}>{r.label}</span>
              {r.values.map((v, i) =>
                v ? (
                  <a
                    key={i}
                    href={v.url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    onPointerEnter={(e) => setTip({ x: e.clientX, y: e.clientY, v, label: r.label, year: data.years[i] })}
                    onPointerMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                    onPointerLeave={() => setTip(null)}
                    onFocus={(e) => {
                      const b = e.currentTarget.getBoundingClientRect()
                      setTip({ x: b.right, y: b.top, v, label: r.label, year: data.years[i] })
                    }}
                    onBlur={() => setTip(null)}
                    style={{ ...NUM, fontSize: 13.5, textAlign: 'right', color: C.text, textDecoration: 'underline dotted', textDecorationColor: `color-mix(in srgb, ${C.accent} 55%, transparent)`, textUnderlineOffset: 4 }}
                  >
                    {money(v.value)}
                  </a>
                ) : (
                  <span key={i} style={{ ...NUM, fontSize: 13.5, textAlign: 'right', color: C.muted }}>
                    –
                  </span>
                ),
              )}
              <Trend values={r.values.map((v) => v?.value ?? null)} />
            </div>
          ))}
          {data.ratios.map((r) => (
            <div key={r.label} style={{ display: 'grid', gridTemplateColumns: cols, gap: 8, alignItems: 'center', padding: '9px 16px', borderBottom: `1px solid ${C.rule}`, background: `color-mix(in srgb, ${C.accentSoft} 50%, transparent)` }}>
              <span style={{ fontFamily: F.body, fontSize: 13.5, fontWeight: 600, color: C.text }} title={r.formula}>
                {r.label}
                <span style={{ display: 'block', fontSize: 11.5, fontWeight: 400, color: C.muted }}>{r.formula}</span>
              </span>
              {r.values.map((v, i) => (
                <span key={i} style={{ ...NUM, fontSize: 13.5, textAlign: 'right', color: C.text }}>
                  {v == null ? '–' : pct(v, 1)}
                </span>
              ))}
              <Trend values={r.values} />
            </div>
          ))}
        </div>
      </Card>
      {tip && (
        <div role="tooltip" style={{ position: 'fixed', left: Math.min(tip.x + 14, window.innerWidth - 270), top: tip.y + 14, zIndex: 50, width: 250, padding: '10px 12px', borderRadius: 10, background: C.raised, border: `1px solid ${C.rule}`, boxShadow: 'var(--shadow-pop)', fontFamily: F.body, fontSize: 12.5, color: C.dim, pointerEvents: 'none' }}>
          <div style={{ fontWeight: 650, color: C.text }}>
            {tip.label}, {fy(tip.year)}
          </div>
          <div style={{ ...NUM, fontSize: 15, fontWeight: 650, color: C.text, margin: '2px 0 6px' }}>{money(tip.v.value)}</div>
          <div>
            Reported in the {tip.v.form ?? 'filing'} filed {day(tip.v.filed)}
          </div>
          <div style={{ ...NUM, fontSize: 11.5, color: C.muted, marginTop: 2 }}>{tip.v.accn}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: C.accent, marginTop: 6 }}>
            Click to open on SEC.gov <ExternalLink size={11} />
          </div>
        </div>
      )}
    </div>
  )
}

/** Oldest to newest, as small bars, the latest year highlighted. */
function Trend({ values }: { values: (number | null)[] }) {
  const v = [...values].reverse()
  const nums = v.filter((x): x is number => x != null)
  if (nums.length < 2) return <span />
  const hi = Math.max(...nums.map(Math.abs)) || 1
  return (
    <span aria-hidden style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-end', gap: 3, height: 22 }}>
      {v.map((x, i) => (
        <span key={i} style={{ width: 8, height: x == null ? 2 : Math.max(2, (Math.abs(x) / hi) * 22), borderRadius: 2, background: x == null ? C.rule : i === v.length - 1 ? C.accent : `color-mix(in srgb, ${C.accent} 35%, ${C.rule})` }} />
      ))}
    </span>
  )
}
