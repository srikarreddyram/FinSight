import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, ask, listDocuments } from './api'
import { AnswerCard } from './components/AnswerCard'
import { AskBar } from './components/AskBar'
import { Backdrop } from './shell/Backdrop'
import { Intro } from './components/Intro'
import { LibraryDrawer } from './components/LibraryDrawer'
import { SourceViewer } from './components/SourceViewer'
import { AnswerSkeleton, Card, ErrorState, PageSkeleton } from './design/primitives'
import { C, F } from './design/tokens'
import { Backtest } from './pages/Backtest'
import { Company } from './pages/Company'
import { Movers } from './pages/Movers'
import { HomeDashboard } from './pages/Home'
import { Risk } from './pages/Risk'
import { SignalLab } from './pages/SignalLab'
import { Watchlist } from './pages/Watchlist'
import { CommandPalette } from './shell/CommandPalette'
import { useRoute } from './shell/routes'
import { TabBar, TopNav } from './shell/Nav'
import { useTheme } from './shell/theme'
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
  const [apiDown, setApiDown] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [theme, setTheme] = useTheme()

  const refreshDocs = useCallback(() => {
    listDocuments()
      .then((d) => {
        setDocs(d)
        setApiDown(false)
      })
      .catch(() => setApiDown(true))
  }, [])
  useEffect(refreshDocs, [refreshDocs])

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
  // '/company/NKE' or '/company/NKE?w=1d' (a mover opens on the window it was found in)
  const [companyPath, companyQuery] = route.startsWith('/company/') ? route.slice('/company/'.length).split('?') : ['', '']
  const companyTicker = companyPath ? decodeURIComponent(companyPath) : null
  const companyWindow = new URLSearchParams(companyQuery ?? '').get('w')
  const companyTab = new URLSearchParams(companyQuery ?? '').get('tab')

  return (
    <div style={{ minHeight: '100vh', color: C.text }}>
      <a href="#main" className="sr-only focus:not-sr-only" style={{ position: 'absolute', zIndex: 80, padding: 8, background: C.surface }}>
        Skip to content
      </a>
      <Backdrop />
      <TopNav route={route} apiDown={apiDown} theme={theme} onTheme={setTheme} onSearch={() => setSearchOpen(true)} onLibrary={() => setLibraryOpen(true)} />
      {/* Room for the phone tab bar under the content. */}
      <div className="pb-[76px] lg:pb-0">
        <div id="main" style={{ position: 'relative' }}>
          {route === '/watchlist' ? (
            <Watchlist />
          ) : route === '/movers' ? (
            <Movers />
          ) : companyTicker ? (
            <Company ticker={companyTicker} hasFilings={indexedTickers.has(companyTicker)} initialWindow={companyWindow === '1d' || companyWindow === '1m' ? companyWindow : '1w'} opened={!!companyWindow} initialTab={companyTab === 'note' ? 'note' : undefined} key={companyTicker} />
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

      <TabBar route={route} onLibrary={() => setLibraryOpen(true)} />
      {searchOpen && <CommandPalette onClose={() => setSearchOpen(false)} />}
      <LibraryDrawer open={libraryOpen} docs={docs} onClose={() => setLibraryOpen(false)} onIngested={refreshDocs} />
    </div>
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
        <>
          <Intro busy={busy} history={history} filings={filings} companies={companies} onAsk={(q) => onAsk(q)} />
          <HomeDashboard />
        </>
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
