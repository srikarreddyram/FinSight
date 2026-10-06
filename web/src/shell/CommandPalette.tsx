// ⌘K: jump to any company in the universe or any page, or hand the text to the Copilot as a question.
import { CornerDownLeft, MessageSquareText, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Avatar } from '../design/primitives'
import { C, F, NUM } from '../design/tokens'
import { getWatchlist } from '../recs/api'
import type { WatchRow } from '../recs/types'
import { GradeChip } from '../pages/shared'
import { go, NAV } from './routes'

interface Item {
  key: string
  group: 'Pages' | 'Companies' | 'Copilot'
  title: string
  subtitle?: string
  right?: React.ReactNode
  icon?: React.ReactNode
  run: () => void
}

let cache: WatchRow[] | null = null

/** Mounted only while open, so every opening starts from an empty query. */
export function CommandPalette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<WatchRow[] | null>(cache)
  const [active, setActive] = useState(0)
  const list = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (cache) return
    getWatchlist()
      .then((r) => {
        cache = r
        setRows(r)
      })
      .catch(() => setRows([]))
  }, [])

  const items = useMemo<Item[]>(() => {
    const t = q.trim().toLowerCase()
    const pages: Item[] = NAV.filter((n) => !t || n.label.toLowerCase().includes(t) || n.description.toLowerCase().includes(t)).map((n) => {
      const Icon = n.icon
      return { key: `page:${n.path}`, group: 'Pages', title: n.label, subtitle: n.description, icon: <Icon size={16} strokeWidth={1.9} />, run: () => go(n.path) }
    })
    let companies: WatchRow[] = []
    if (t && rows) {
      const score = (r: WatchRow) => {
        const tk = r.ticker.toLowerCase()
        const name = (r.name ?? '').toLowerCase()
        if (tk === t) return 0
        if (tk.startsWith(t)) return 1
        if (name.startsWith(t)) return 2
        if (name.includes(t)) return 3
        return 9
      }
      companies = rows
        .map((r) => [score(r), r] as const)
        .filter(([s]) => s < 9)
        .sort((a, b) => a[0] - b[0] || a[1].ticker.localeCompare(b[1].ticker))
        .slice(0, 8)
        .map(([, r]) => r)
    }
    const comp: Item[] = companies.map((r) => ({
      key: `co:${r.ticker}`,
      group: 'Companies',
      title: r.ticker,
      subtitle: [r.name, r.index, r.sector].filter(Boolean).join(' · '),
      right: <GradeChip grade={r.risk_grade} compact />,
      run: () => go(`/company/${encodeURIComponent(r.ticker)}`),
    }))
    const ask: Item[] = t.length > 3 ? [{ key: 'ask', group: 'Copilot', title: `Ask the filings: “${q.trim()}”`, icon: <MessageSquareText size={16} strokeWidth={1.9} />, run: () => (window.location.href = `${import.meta.env.BASE_URL}?q=${encodeURIComponent(q.trim())}`) }] : []
    return t ? [...comp, ...pages, ...ask] : pages
  }, [q, rows])

  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const choose = (it: Item | undefined) => {
    if (!it) return
    onClose()
    it.run()
  }
  return (
    <div role="dialog" aria-modal="true" aria-label="Search" style={{ position: 'fixed', inset: 0, zIndex: 70, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: '12vh 16px 16px' }}>
      <button type="button" aria-label="Close search" onClick={onClose} className="anim-fade-in" style={{ position: 'absolute', inset: 0, background: 'rgb(8 10 14 / 0.45)', border: 'none', cursor: 'default' }} />
      <div className="anim-pop" style={{ position: 'relative', width: '100%', maxWidth: 620, background: C.surface, border: `1px solid ${C.rule}`, borderRadius: 14, boxShadow: 'var(--shadow-pop)', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 16px', height: 54, borderBottom: `1px solid ${C.rule}` }}>
          <Search size={17} color={C.muted} />
          <input
            autoFocus
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setActive(0)
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive((a) => Math.min(items.length - 1, a + 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((a) => Math.max(0, a - 1))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                choose(items[active])
              } else if (e.key === 'Escape') {
                onClose()
              }
            }}
            placeholder="Search companies by ticker or name, or jump to a page…"
            aria-label="Search"
            style={{ flex: 1, height: '100%', background: 'transparent', border: 'none', outline: 'none', fontFamily: F.body, fontSize: 15, color: C.text }}
          />
          <span className="kbd">Esc</span>
        </div>
        <div ref={list} style={{ maxHeight: '52vh', overflowY: 'auto', padding: 6 }}>
          {items.length === 0 && <div style={{ padding: '28px 12px', textAlign: 'center', fontFamily: F.body, fontSize: 13.5, color: C.muted }}>{rows ? 'No companies or pages match.' : 'Loading companies…'}</div>}
          {items.map((it, i) => {
            const header = i === 0 || items[i - 1].group !== it.group ? it.group : null
            const on = i === active
            return (
              <div key={it.key}>
                {header && <div style={{ fontFamily: F.body, fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: C.muted, padding: '10px 10px 4px' }}>{header}</div>}
                <button
                  type="button"
                  data-index={i}
                  onMouseMove={() => setActive(i)}
                  onClick={() => choose(it)}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '8px 10px',
                    borderRadius: 8,
                    border: 'none',
                    textAlign: 'left',
                    cursor: 'pointer',
                    background: on ? C.hover : 'transparent',
                    color: C.text,
                  }}
                >
                  {it.icon ? (
                    <span style={{ color: on ? C.accent : C.muted, display: 'flex' }}>{it.icon}</span>
                  ) : (
                    <span style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 92 }}>
                      <Avatar ticker={it.title} name={it.subtitle?.split(' · ')[0]} size={28} />
                      <span style={{ ...NUM, fontSize: 12.5, fontWeight: 600, color: C.text }}>{it.title}</span>
                    </span>
                  )}
                  <span style={{ flex: 1, minWidth: 0 }}>
                    {it.icon && <span style={{ display: 'block', fontFamily: F.body, fontSize: 13.5, fontWeight: 500 }}>{it.title}</span>}
                    {it.subtitle && <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 12.5, color: C.muted }}>{it.subtitle}</span>}
                  </span>
                  {it.right}
                  {on && <CornerDownLeft size={14} color={C.muted} />}
                </button>
              </div>
            )
          })}
        </div>
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', padding: '8px 14px', borderTop: `1px solid ${C.rule}`, background: C.raised, fontFamily: F.body, fontSize: 12, color: C.muted }}>
          <span>
            <span className="kbd">↑</span> <span className="kbd">↓</span> to move
          </span>
          <span>
            <span className="kbd">↵</span> to open
          </span>
          <span style={{ marginLeft: 'auto' }}>{rows ? `${rows.length.toLocaleString()} companies` : ''}</span>
        </div>
      </div>
    </div>
  )
}
