import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, ask, listDocuments } from './api'
import { AnswerCard } from './components/AnswerCard'
import { AskBar } from './components/AskBar'
import { Intro } from './components/Intro'
import { LibraryDrawer } from './components/LibraryDrawer'
import { SourceViewer } from './components/SourceViewer'
import { TracePanel } from './components/TracePanel'
import { DefaultWash, EdgeBezel, HeaderStripe } from './design/chrome'
import { AnswerSkeleton, Card, ErrorState, PageSkeleton, SectionLabel, Segmented } from './design/primitives'
import { C, F, NUM } from './design/tokens'
import { Backtest } from './pages/Backtest'
import { Company } from './pages/Company'
import { Methodology } from './pages/Methodology'
import { Risk } from './pages/Risk'
import { SignalLab } from './pages/SignalLab'
import { Watchlist } from './pages/Watchlist'
import type { Answer, Citation, DocumentInfo, Run } from './types'

// Hash routes keep the dashboard a static single page: '#/watchlist', '#/company/AAPL'. No hash is the Copilot.
const NAV = [
  { path: '', label: 'Copilot' },
  { path: '/watchlist', label: 'Watchlist' },
  { path: '/signals', label: 'Signal Lab' },
  { path: '/backtest', label: 'Backtest' },
  { path: '/risk', label: 'Risk' },
  { path: '/methodology', label: 'Methodology' },
] as const

function useRoute(): string {
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

  const refreshDocs = useCallback(() => {
    listDocuments()
      .then((d) => {
        setDocs(d)
        setApiDown(false)
      })
      .catch(() => setApiDown(true))
  }, [])
  useEffect(refreshDocs, [refreshDocs])

  const indexed = docs.filter((d) => d.indexed)
  const companies = new Set(indexed.map((d) => d.company)).size
  const route = useRoute()
  const section = route.startsWith('/company/') ? '/watchlist' : route
  const indexedTickers = new Set(indexed.map((d) => d.ticker))

  return (
    <div style={{ minHeight: '100vh', position: 'relative', color: C.text }}>
      {/* Static chrome, rendered once and never tied to any view's animation. */}
      <DefaultWash />
      <EdgeBezel />

      <header style={{ position: 'sticky', top: 0, zIndex: 30, background: `color-mix(in srgb, ${C.bg} 86%, transparent)`, backdropFilter: 'blur(10px)' }}>
        <div style={{ maxWidth: 1400, margin: '0 auto', display: 'flex', alignItems: 'center', gap: 16, padding: '12px 20px' }}>
          <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', color: C.text }}>
            <img src="/favicon.svg" alt="" width={26} height={26} />
            <span style={{ fontFamily: F.display, fontWeight: 700, fontSize: 22, letterSpacing: '0.06em', textTransform: 'uppercase' }}>FinSight</span>
          </a>
          <span className="hidden sm:inline" style={{ ...NUM, fontSize: 10.5, color: apiDown ? C.red : C.muted, letterSpacing: '0.08em' }}>
            {apiDown ? 'API OFFLINE' : `${indexed.length} FILINGS · ${companies} COMPANIES`}
          </span>
          <nav aria-label="Sections" style={{ display: 'flex', gap: 18, marginLeft: 12, overflowX: 'auto' }}>
            {NAV.map((n) => (
              <a key={n.path} href={n.path ? `#${n.path}` : '/'} className="nav-link" aria-current={section === n.path ? 'page' : undefined}>
                {n.label}
              </a>
            ))}
          </nav>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
            <HeaderButton onClick={() => setLibraryOpen(true)}>Library</HeaderButton>
          </div>
        </div>
        <HeaderStripe />
      </header>

      <div style={{ position: 'relative', zIndex: 1 }}>
        {route === '/watchlist' ? (
          <Watchlist />
        ) : route.startsWith('/company/') ? (
          <Company ticker={decodeURIComponent(route.slice('/company/'.length))} hasFilings={indexedTickers.has(decodeURIComponent(route.slice('/company/'.length)))} />
        ) : route === '/signals' ? (
          <SignalLab />
        ) : route === '/backtest' ? (
          <Backtest />
        ) : route === '/risk' ? (
          <Risk />
        ) : route === '/methodology' ? (
          <Methodology />
        ) : (
          <Workspace apiDown={apiDown} pending={pending} onPendingUsed={() => setPending(null)} />
        )}
      </div>

      <LibraryDrawer open={libraryOpen} docs={docs} onClose={() => setLibraryOpen(false)} onIngested={refreshDocs} />
    </div>
  )
}

function HeaderButton({ children, onClick }: { children: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover-lift"
      style={{
        fontFamily: F.mono,
        fontSize: 10.5,
        letterSpacing: '0.2em',
        textTransform: 'uppercase',
        padding: '7px 14px',
        borderRadius: 6,
        cursor: 'pointer',
        background: C.surface,
        color: C.dim,
        border: `1px solid ${C.rule}`,
      }}
    >
      {children}
    </button>
  )
}

/** The working app: ask on the left, source on the right. */
function Workspace({ apiDown, pending, onPendingUsed }: { apiDown: boolean; pending: string | null; onPendingUsed: () => void }) {
  const [run, setRun] = useState<Run>('E')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Citation | null>(null)
  const [history, setHistory] = useState<string[]>(loadHistory)
  const abort = useRef<AbortController | null>(null)

  const onAsk = async (q: string, withRun: Run = run) => {
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
      const a = await ask(q, withRun, ctrl.signal)
      setAnswer(a)
      setSelected((a.error ? a.retrieved[0] : a.refused ? a.closest[0] : a.citations[0]) ?? null)
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      if (e instanceof ApiError && e.status === 429) {
        setError(`The free-tier LLM quota is used up for today (${e.message})`)
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

  // §8 alternate view: the same question through the naive baseline, one click away.
  const switchRun = (r: Run) => {
    setRun(r)
    if (question) void onAsk(question, r)
  }

  const started = busy || answer || error
  return (
    <main style={{ maxWidth: 1400, margin: '0 auto', padding: '20px 20px 40px' }}>
      {apiDown && (
        <div style={{ marginBottom: 16 }}>
          <ErrorState title="Can’t reach the FinSight API" message="The web app is up but the backend isn’t" hint="start it with `uv run uvicorn app.api:app`, then reload" />
        </div>
      )}

      {!started ? (
        <Intro busy={busy} history={history} onAsk={(q) => onAsk(q)} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <section style={{ minWidth: 0, display: 'grid', gap: 14, alignContent: 'start' }}>
            <AskBar key={question} busy={busy} initial={question} onAsk={(q) => onAsk(q)} showExamples={false} />
            {/* Page-context label on the left, the view toggle on the right. */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <SectionLabel color={C.muted}>{run === 'E' ? 'Full pipeline · run E' : 'Naive baseline · run A'}</SectionLabel>
              <Segmented<Run>
                value={run}
                onChange={switchRun}
                disabled={busy}
                options={[
                  { value: 'E', label: 'Full system', title: 'Docling tables, hybrid search, filters, reranking' },
                  { value: 'A', label: 'Naive RAG', title: 'Plain PDF text, fixed chunks, dense search only' },
                ]}
              />
            </div>
            {busy && <AnswerSkeleton />}
            {error && <ErrorState message={error} hint="try again once the quota resets or the backend is back" />}
            {answer && (
              <>
                <AnswerCard answer={answer} selected={selected} onCite={setSelected} onRetry={() => onAsk(question)} />
                <TracePanel answer={answer} onCite={setSelected} />
              </>
            )}
          </section>
          <section className="lg:sticky lg:top-[76px] lg:h-[calc(100vh-96px)]" style={{ minWidth: 0 }}>
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
