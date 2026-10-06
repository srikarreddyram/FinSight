// Navigation: a top bar with text tabs and a wide search on desktop; on phones, a slim top bar and a bottom
// tab bar with a "More" sheet for the rest.
import { Library, Menu, Monitor, Moon, Search, Sun, X } from 'lucide-react'
import { useState } from 'react'
import { DEMO } from '../demo'
import { C, F } from '../design/tokens'

const DEMO_AS_OF = import.meta.env.VITE_DEMO_AS_OF ?? 'the build date'
import { NAV, sectionOf } from './routes'
import type { ThemeChoice } from './theme'
import { useEscape } from './useEscape'

const PRIMARY = ['', '/watchlist', '/movers', '/risk'] // the bottom bar's tabs; the rest sit under More
const isMac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)

interface Props {
  route: string
  apiDown: boolean
  theme: ThemeChoice
  onTheme: (t: ThemeChoice) => void
  onSearch: () => void
  onLibrary: () => void
}

const NEXT: Record<ThemeChoice, ThemeChoice> = { system: 'light', light: 'dark', dark: 'system' }
const THEME_ICON = { light: Sun, dark: Moon, system: Monitor }
const THEME_LABEL = { light: 'Light theme', dark: 'Dark theme', system: 'Theme follows the system' }

function ThemeButton({ theme, onTheme }: { theme: ThemeChoice; onTheme: (t: ThemeChoice) => void }) {
  const Icon = THEME_ICON[theme]
  return (
    <button type="button" className="btn btn-ghost btn-icon" onClick={() => onTheme(NEXT[theme])} title={`${THEME_LABEL[theme]} (click to change)`} aria-label={THEME_LABEL[theme]}>
      <Icon size={18} />
    </button>
  )
}

function Brand() {
  return (
    <a href={import.meta.env.BASE_URL} style={{ display: 'flex', alignItems: 'center', gap: 9, textDecoration: 'none', color: C.text, flex: 'none' }}>
      <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={28} height={28} style={{ borderRadius: 8 }} />
      <span style={{ fontFamily: F.display, fontWeight: 700, fontSize: 18, letterSpacing: '-0.02em' }}>FinSight</span>
    </a>
  )
}

export function TopNav({ route, apiDown, theme, onTheme, onSearch, onLibrary }: Props) {
  const current = sectionOf(route)
  return (
    <header style={{ position: 'sticky', top: 0, zIndex: 30, background: C.surface, borderBottom: `1px solid ${C.rule}` }}>
      {DEMO && (
        <div style={{ background: C.accentSoft, color: C.dim, fontFamily: F.body, fontSize: 12.5, textAlign: 'center', padding: '6px 16px' }}>
          Demo snapshot with prices to {DEMO_AS_OF}.{' '}
          <a href="https://github.com/srikarreddyram/FinSight" style={{ color: C.accent, fontWeight: 600 }}>
            Run it locally
          </a>{' '}
          for live prices and any question.
        </div>
      )}
      <div style={{ maxWidth: 1440, margin: '0 auto', height: 64, display: 'flex', alignItems: 'center', gap: 28, padding: '0 clamp(16px, 2.4vw, 28px)' }}>
        <Brand />
        <nav aria-label="Main" className="hidden lg:flex" style={{ alignItems: 'center', gap: 24, height: '100%' }}>
          {NAV.map((n) => (
            <a key={n.path} href={n.path ? `#${n.path}` : import.meta.env.BASE_URL} className="topnav-link" aria-current={current?.path === n.path ? 'page' : undefined} title={n.description}>
              {n.label}
            </a>
          ))}
        </nav>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <button
            type="button"
            onClick={onSearch}
            aria-label="Search stocks and pages"
            className="hidden sm:flex"
            style={{ alignItems: 'center', gap: 10, width: 'min(320px, 34vw)', height: 40, padding: '0 14px', borderRadius: 10, border: '1px solid transparent', background: 'var(--search)', color: C.muted, cursor: 'pointer', fontFamily: F.body, fontSize: 14 }}
          >
            <Search size={17} />
            <span className="truncate" style={{ flex: 1, textAlign: 'left' }}>
              Search stocks…
            </span>
            <span className="kbd">{isMac ? '⌘K' : 'Ctrl K'}</span>
          </button>
          <button type="button" className="btn btn-ghost btn-icon sm:hidden" onClick={onSearch} aria-label="Search">
            <Search size={19} />
          </button>
          <button type="button" className="btn btn-ghost btn-icon hidden lg:inline-flex" onClick={onLibrary} title="Filing library" aria-label="Filing library">
            <Library size={18} />
          </button>
          <ThemeButton theme={theme} onTheme={onTheme} />
          <span
            title={apiDown ? 'API offline' : 'Connected'}
            aria-label={apiDown ? 'API offline' : 'Connected'}
            style={{ width: 8, height: 8, borderRadius: 999, marginLeft: 4, background: apiDown ? C.red : C.accent, boxShadow: `0 0 0 3px color-mix(in srgb, ${apiDown ? C.red : C.accent} 20%, transparent)` }}
          />
        </div>
      </div>
    </header>
  )
}

export function TabBar({ route, onLibrary }: { route: string; onLibrary: () => void }) {
  const [more, setMore] = useState(false)
  useEscape(more, () => setMore(false))
  const current = sectionOf(route)
  const primary = NAV.filter((n) => PRIMARY.includes(n.path))
  const rest = NAV.filter((n) => !PRIMARY.includes(n.path))
  return (
    <>
      <nav aria-label="Main" className="flex lg:hidden" style={{ position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 40, background: C.surface, borderTop: `1px solid ${C.rule}`, paddingBottom: 'env(safe-area-inset-bottom)' }}>
        {primary.map((n) => {
          const Icon = n.icon
          return (
            <a key={n.path} href={n.path ? `#${n.path}` : import.meta.env.BASE_URL} className="tabbar-link" aria-current={current?.path === n.path ? 'page' : undefined}>
              <Icon size={21} strokeWidth={current?.path === n.path ? 2.3 : 1.8} />
              {n.label}
            </a>
          )
        })}
        <button type="button" className="tabbar-link" aria-current={rest.some((n) => n.path === current?.path) ? 'page' : undefined} onClick={() => setMore(true)}>
          <Menu size={21} strokeWidth={1.8} />
          More
        </button>
      </nav>
      {more && (
        <div className="lg:hidden" role="dialog" aria-modal="true" aria-label="More" style={{ position: 'fixed', inset: 0, zIndex: 60 }}>
          <button type="button" aria-label="Close" onClick={() => setMore(false)} className="anim-fade-in" style={{ position: 'absolute', inset: 0, background: 'rgb(8 10 14 / 0.45)', border: 'none' }} />
          <div className="anim-fade-up" style={{ position: 'absolute', left: 0, right: 0, bottom: 0, background: C.surface, borderRadius: '18px 18px 0 0', padding: '10px 12px calc(16px + env(safe-area-inset-bottom))', boxShadow: 'var(--shadow-pop)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 6px 10px' }}>
              <span style={{ fontFamily: F.body, fontSize: 16, fontWeight: 600, color: C.text }}>More</span>
              <button type="button" className="btn btn-ghost btn-icon" onClick={() => setMore(false)} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            {rest.map((n) => {
              const Icon = n.icon
              return (
                <a key={n.path} href={`#${n.path}`} className="menu-link" onClick={() => setMore(false)} aria-current={current?.path === n.path ? 'page' : undefined}>
                  <Icon size={19} color={C.accent} /> {n.label}
                </a>
              )
            })}
            <button
              type="button"
              className="menu-link"
              onClick={() => {
                setMore(false)
                onLibrary()
              }}
            >
              <Library size={19} color={C.accent} /> Filing library
            </button>
          </div>
        </div>
      )}
    </>
  )
}
