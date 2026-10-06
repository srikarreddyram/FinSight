// The left rail: brand, grouped navigation, the filing library, and the data and theme status at the bottom.
import { Library, Monitor, Moon, Sun } from 'lucide-react'
import { C, F, NUM } from '../design/tokens'
import { monthLabel } from '../recs/format'
import type { Meta } from '../recs/types'
import { NAV_GROUPS, sectionOf } from './routes'
import type { ThemeChoice } from './theme'

interface Props {
  route: string
  meta: Meta | null
  apiDown: boolean
  filings: number
  theme: ThemeChoice
  onTheme: (t: ThemeChoice) => void
  onLibrary: () => void
  onNavigate?: () => void
}

export function Sidebar({ route, meta, apiDown, filings, theme, onTheme, onLibrary, onNavigate }: Props) {
  const current = sectionOf(route)
  return (
    <nav aria-label="Main" className="sidebar" style={{ display: 'flex', flexDirection: 'column', height: '100%', width: 232 }}>
      <a href="/" onClick={onNavigate} style={{ display: 'flex', alignItems: 'center', gap: 10, height: 56, padding: '0 18px', textDecoration: 'none', color: C.text, flex: 'none' }}>
        <img src="/favicon.svg" alt="" width={24} height={24} style={{ borderRadius: 6 }} />
        <span style={{ fontFamily: F.display, fontWeight: 700, fontSize: 16, letterSpacing: '-0.01em' }}>FinSight</span>
        <span style={{ fontFamily: F.body, fontSize: 11, fontWeight: 500, color: C.muted, border: `1px solid ${C.rule}`, borderRadius: 5, padding: '0 5px', lineHeight: '17px' }}>Research</span>
      </a>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px 12px' }}>
        {NAV_GROUPS.map((g) => (
          <div key={g.label} style={{ marginTop: 14 }}>
            <div style={{ fontFamily: F.body, fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: C.muted, padding: '0 10px 6px' }}>{g.label}</div>
            <div style={{ display: 'grid', gap: 2 }}>
              {g.items.map((n) => {
                const Icon = n.icon
                return (
                  <a key={n.path} href={n.path ? `#${n.path}` : '/'} onClick={onNavigate} className="side-link" aria-current={current?.path === n.path ? 'page' : undefined} title={n.description}>
                    <Icon size={16} strokeWidth={1.9} />
                    {n.label}
                  </a>
                )
              })}
              {g.label === 'Library' && (
                <button
                  type="button"
                  className="side-link"
                  onClick={() => {
                    onLibrary()
                    onNavigate?.()
                  }}
                  style={{ background: 'transparent', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}
                  title="Indexed filings and uploads"
                >
                  <Library size={16} strokeWidth={1.9} />
                  Filing library
                  <span style={{ ...NUM, marginLeft: 'auto', fontSize: 11.5, color: C.muted }}>{filings || ''}</span>
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div style={{ flex: 'none', borderTop: `1px solid ${C.rule}`, padding: '12px 14px 14px', display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
          <span
            aria-hidden
            style={{ width: 7, height: 7, borderRadius: 999, marginTop: 6, flex: 'none', background: apiDown ? C.red : C.verified, boxShadow: `0 0 0 3px color-mix(in srgb, ${apiDown ? C.red : C.verified} 18%, transparent)` }}
          />
          <div style={{ fontFamily: F.body, fontSize: 12, lineHeight: 1.5, color: C.muted, minWidth: 0 }}>
            {apiDown ? (
              <span style={{ color: C.red }}>API offline</span>
            ) : meta ? (
              <>
                <span style={{ color: C.dim, fontWeight: 500 }}>Data as of {monthLabel(meta.as_of)}</span>
                <br />
                {meta.companies.toLocaleString()} companies · S&amp;P 500, 400, 600
              </>
            ) : (
              'Connecting…'
            )}
          </div>
        </div>
        <ThemeSwitch value={theme} onChange={onTheme} />
      </div>
    </nav>
  )
}

function ThemeSwitch({ value, onChange }: { value: ThemeChoice; onChange: (t: ThemeChoice) => void }) {
  const options: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
    { value: 'light', label: 'Light theme', icon: Sun },
    { value: 'dark', label: 'Dark theme', icon: Moon },
    { value: 'system', label: 'Match the system', icon: Monitor },
  ]
  return (
    <div role="radiogroup" aria-label="Theme" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', background: C.raised, border: `1px solid ${C.rule}`, borderRadius: 8, padding: 2, gap: 2 }}>
      {options.map((o) => {
        const Icon = o.icon
        const on = value === o.value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            aria-label={o.label}
            title={o.label}
            onClick={() => onChange(o.value)}
            style={{
              height: 26,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 6,
              cursor: 'pointer',
              background: on ? C.surface : 'transparent',
              border: `1px solid ${on ? C.rule : 'transparent'}`,
              boxShadow: on ? 'var(--shadow-card)' : 'none',
              color: on ? C.text : C.muted,
            }}
          >
            <Icon size={14} strokeWidth={2} />
          </button>
        )
      })}
    </div>
  )
}
