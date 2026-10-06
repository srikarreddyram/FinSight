// Hash routes keep the app a static single page: '#/watchlist', '#/company/AAPL'. No hash is the Copilot.
import { useEffect, useState } from 'react'
import { ChartLine, FlaskConical, ListOrdered, type LucideIcon, MessageSquareText, ShieldAlert } from 'lucide-react'

export interface NavItem {
  path: string
  label: string
  icon: LucideIcon
  description: string
}

export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: 'Research',
    items: [
      { path: '', label: 'Copilot', icon: MessageSquareText, description: 'Ask questions about company filings' },
      { path: '/watchlist', label: 'Watchlist', icon: ListOrdered, description: 'Ranked companies with risk grades' },
    ],
  },
  {
    label: 'Models',
    items: [
      { path: '/signals', label: 'Signal Lab', icon: FlaskConical, description: 'Signal performance by year and index' },
      { path: '/backtest', label: 'Backtest', icon: ChartLine, description: 'Long-short performance after costs' },
      { path: '/risk', label: 'Risk', icon: ShieldAlert, description: 'Risk grades across the universe' },
    ],
  },
  { label: 'Library', items: [] },
]
export const NAV: NavItem[] = NAV_GROUPS.flatMap((g) => g.items)

export function useRoute(): string {
  const read = () => window.location.hash.replace(/^#/, '')
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const on = () => {
      setRoute(read())
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export function go(path: string) {
  if (path === '') {
    // The Copilot lives at the bare URL; keep any ?q= the person is on.
    window.location.hash = ''
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  } else {
    window.location.hash = path
  }
}

/** The nav item a route belongs to: a company page sits under the Watchlist. */
export function sectionOf(route: string): NavItem | undefined {
  const path = route.startsWith('/company/') ? '/watchlist' : route
  return NAV.find((n) => n.path === path) ?? (route === '' ? NAV[0] : undefined)
}
