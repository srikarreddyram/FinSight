import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronRight, Menu, Search } from 'lucide-react'
import { ApiError, ask, listDocuments } from './api'
import { AnswerCard } from './components/AnswerCard'
import { AskBar } from './components/AskBar'
import { Intro } from './components/Intro'
import { LibraryDrawer } from './components/LibraryDrawer'
import { SourceViewer } from './components/SourceViewer'
import { AnswerSkeleton, Card, ErrorState, PageSkeleton } from './design/primitives'
import { C, F } from './design/tokens'
import { Backtest } from './pages/Backtest'
import { Company } from './pages/Company'
import { Risk } from './pages/Risk'
import { SignalLab } from './pages/SignalLab'
import { Watchlist } from './pages/Watchlist'
import { getMeta } from './recs/api'
import type { Meta } from './recs/types'
import { CommandPalette } from './shell/CommandPalette'
import { NAV_GROUPS, sectionOf, useRoute } from './shell/routes'
import { Sidebar } from './shell/Sidebar'
import { useTheme } from './shell/theme'
import { useEscape } from './shell/useEscape'
import type { Answer, Citation, DocumentInfo } from './types'

const HISTORY_KEY = 'finsight.history'

function loadHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveHistory(h: string[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, 8)))
  } catch {
    /* private mode: history is a convenience only */
  }
}

export default function App() {
  // A shared /?q=... link asks its question on load.
  const [pending, setPending] = useState<string | null>(() => new URLSearchParams(window.location.search).get('q'))
  const [docs, setDocs] = useState<DocumentInfo[]>([])
  const [meta, setMeta] = useState<Meta | null>(null)
  const [apiDown, setApiDown] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [theme, setTheme] = useTheme()
  const closeMenu = useCallback(() => setMenuOpen(false), [])
  useEscape(menuOpen, closeMenu)

  const refreshDocs = useCallback(() => {
    listDocuments()
      .then((d) => {
        setDocs(d)
        setApiDown(false)
      })
      .catch(() => setApiDown(true))
  }, [])
  useEffect(refreshDocs, [refreshDocs])
  useEffect(() => {
    getMeta()
      .then(setMeta)
      .catch(() => setMeta(null))
  }, [])

  // ⌘K / Ctrl+K opens search from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const indexed = docs.filter((d) => d.indexed)
  const route = useRoute()
  const indexedTickers = new Set(indexed.map((d) => d.ticker))
  const companyTicker = route.startsWith('/company/') ? decodeURIComponent(route.slice('/company/'.length)) : null

  const sidebar = (onNavigate?: () => void) => (
    <Sidebar route={route} meta={meta} apiDown={apiDown} filings={indexed.length} theme={theme} onTheme={setTheme} onLibrary={() => setLibraryOpen(true)} onNavigate={onNavigate} />
  )

  return (
    <div style={{ minHeight: '100vh', color: C.text }}>
      <a href="#main" className="sr-only focus:not-sr-only" style={{ position: 'absolute', zIndex: 80, padding: 8, background: C.surface }}>
        Skip to content
      </a>
      {/* Desktop: a fixed rail. Narrow screens: the same rail as a drawer behind the menu button. */}
      <div className="hidden lg:block" style={{ position: 'fixed', top: 0, bottom: 0, left: 0, zIndex: 40 }}>
        {sidebar()}
      </div>
      {menuOpen && (
        <div className="lg:hidden" style={{ position: 'fixed', inset: 0, zIndex: 60 }} role="dialog" aria-modal="true" aria-label="Navigation">
          <button type="button" aria-label="Close navigation" onClick={() => setMenuOpen(false)} className="anim-fade-in" style={{ position: 'absolute', inset: 0, background: 'rgb(8 10 14 / 0.45)', border: 'none' }} />
          <div className="anim-slide-left" style={{ position: 'absolute', top: 0, bottom: 0, left: 0, boxShadow: 'var(--shadow-pop)' }}>
            {sidebar(() => setMenuOpen(false))}
          </div>
        </div>
      )}

      <div className="lg:pl-[232px]">
        <TopBar route={route} company={companyTicker} onMenu={() => setMenuOpen(true)} onSearch={() => setSearchOpen(true)} />
        <div id="main" style={{ position: 'relative' }}>
          {route === '/watchlist' ? (
            <Watchlist />
          ) : companyTicker ? (
            <Company ticker={companyTicker} hasFilings={indexedTickers.has(companyTicker)} />
          ) : route === '/signals' ? (
            <SignalLab />
          ) : route === '/backtest' ? (
            <Backtest />
          ) : route === '/risk' ? (
            <Risk />
          ) : (
            <Workspace apiDown={apiDown} filings={indexed.length} companies={new Set(indexed.map((d) => d.company)).size} pending={pending} onPendingUsed={() => setPending(null)} />
          )}
        </div>
      </div>

      {searchOpen && <CommandPalette onClose={() => setSearchOpen(false)} />}
      <LibraryDrawer open={libraryOpen} docs={docs} onClose={() => setLibraryOpen(false)} onIngested={refreshDocs} />
    </div>
  )
}

/** Sticky bar over the content: where you are, and search. */
function TopBar({ route, company, onMenu, onSearch }: { route: string; company: string | null; onMenu: () => void; onSearch: () => void }) {
  const section = sectionOf(route)
  const group = NAV_GROUPS.find((g) => g.items.some((n) => n.path === section?.path))
  const isMac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)
  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 30,
        height: 56,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '0 clamp(16px, 2.4vw, 28px)',
        background: `color-mix(in srgb, ${C.bg} 88%, transparent)`,
        backdropFilter: 'blur(10px)',
        borderBottom: `1px solid ${C.rule}`,
      }}
    >
      <button type="button" className="btn btn-ghost btn-icon lg:hidden" aria-label="Open navigation" onClick={onMenu}>
        <Menu size={18} />
      </button>
      <a href="/" className="flex lg:hidden" style={{ alignItems: 'center' }} aria-label="FinSight home">
        <img src="/favicon.svg" alt="" width={22} height={22} style={{ borderRadius: 5 }} />
      </a>
      <nav aria-label="Breadcrumb" className="hidden sm:flex" style={{ alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 13.5, minWidth: 0 }}>
        {group && <span style={{ color: C.muted }}>{group.label}</span>}
        {group && <ChevronRight size={14} color={C.muted} />}
        {company ? (
          <>
            <a href="#/watchlist" style={{ color: C.muted, textDecoration: 'none' }}>
              Watchlist
            </a>
            <ChevronRight size={14} color={C.muted} />
            <span style={{ color: C.text, fontWeight: 600 }}>{company}</span>
          </>
        ) : (
          <span style={{ color: C.text, fontWeight: 600 }}>{section?.label ?? 'FinSight'}</span>
        )}
      </nav>
      <button
        type="button"
        onClick={onSearch}
        className="control"
        aria-label="Search companies and pages"
        style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8, width: 'min(340px, 52vw)', cursor: 'pointer', color: C.muted, textAlign: 'left' }}
      >
        <Search size={15} />
        <span className="truncate" style={{ flex: 1 }}>
          Search companies…
        </span>
        <span className="kbd hidden sm:inline">{isMac ? '⌘K' : 'Ctrl K'}</span>
      </button>
    </header>
  )
}

/** The working app: ask on the left, source on the right. */
function Workspace({ apiDown, filings, companies, pending, onPendingUsed }: { apiDown: boolean; filings: number; companies: number; pending: string | null; onPendingUsed: () => void }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Citation | null>(null)
  const [history, setHistory] = useState<string[]>(loadHistory)
  const abort = useRef<AbortController | null>(null)

  const onAsk = async (q: string) => {
    abort.current?.abort()
    const ctrl = new AbortController()
    abort.current = ctrl
    setQuestion(q)
    window.history.replaceState(null, '', `?${new URLSearchParams({ q })}`)
    setBusy(true)
    setError(null)
    setAnswer(null)
    setSelected(null)
    const h = [q, ...history.filter((x) => x !== q)]
    setHistory(h)
    saveHistory(h)
    try {
      const a = await ask(q, 'E', ctrl.signal) // the full pipeline; run A (naive RAG) is for evaluation only
      setAnswer(a)
      setSelected((a.error ? a.retrieved[0] : a.refused ? a.closest[0] : a.citations[0]) ?? null)
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      if (e instanceof ApiError && e.status === 429) {
        setError(`The daily question limit has been reached (${e.message})`)
      } else {
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      if (abort.current === ctrl) setBusy(false)
    }
  }

  // A question from a shared ?q= link.
  useEffect(() => {
    if (pending) {
      onPendingUsed()
      void onAsk(pending)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending])

  const started = busy || answer || error
  return (
    <main style={{ maxWidth: 1440, margin: '0 auto', padding: 'clamp(16px, 2.4vw, 28px)' }}>
      {apiDown && (
        <div style={{ marginBottom: 16 }}>
          <ErrorState
            title="Can’t reach the FinSight API"
            message="The web app is up but the backend isn’t"
            hint={
              <>
                start it with <code style={{ fontFamily: F.code, fontSize: 12 }}>uv run uvicorn app.api:app</code>, then reload
              </>
            }
          />
        </div>
      )}

      {!started ? (
        <Intro busy={busy} history={history} filings={filings} companies={companies} onAsk={(q) => onAsk(q)} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <section style={{ minWidth: 0, display: 'grid', gap: 14, alignContent: 'start' }}>
            <AskBar key={question} busy={busy} initial={question} onAsk={(q) => onAsk(q)} showExamples={false} />
            {busy && <AnswerSkeleton />}
            {error && <ErrorState title="Couldn’t get an answer" message={error} hint="try again in a moment" />}
            {answer && (
              <>
                <AnswerCard answer={answer} selected={selected} onCite={setSelected} onRetry={() => onAsk(question)} />
              </>
            )}
          </section>
          <section className="lg:sticky lg:top-[80px] lg:h-[calc(100vh-104px)]" style={{ minWidth: 0 }}>
            <Card style={{ height: '100%', minHeight: '70vh', overflow: 'hidden' }}>
              {busy ? (
                <div style={{ padding: 12, height: '100%' }}>
                  <PageSkeleton />
                </div>
              ) : (
                <SourceViewer key={selected ? `${selected.doc_id}-${selected.page}-${selected.id}` : 'none'} citation={selected} />
              )}
            </Card>
          </section>
        </div>
      )}
    </main>
  )
}
