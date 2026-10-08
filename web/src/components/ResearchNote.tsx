// "Research note" on a company page: a bull case, a bear case and what to watch, written on request from the
// latest 10-K, the financial statements, recent news and FinSight's data, with every point citing the sources
// listed under it.
import { ArrowDownRight, ArrowUpRight, Check, ChevronDown, Eye, ExternalLink, LoaderCircle, RefreshCw, Sparkles } from 'lucide-react'
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { gatherSources, getNote, writeNote } from '../analyst/api'
import type { NoteItem, NotePoint, NoteSources, ResearchNote as Note } from '../analyst/types'
import { ApiError } from '../api'
import { DEMO } from '../demo'
import { Card, PanelTitle, SectionLabel, Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { useData } from '../pages/data'
import { Cited } from './Cited'

const PREFIX = 'src'
const frame: CSSProperties = { borderRadius: 14, border: `1px solid ${C.edge}`, background: `linear-gradient(180deg, ${C.accentSoft} 0%, ${C.surface} 70%)`, padding: 18 }
const date = (iso: string, year = true) =>
  new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(year ? { year: 'numeric' } : {}), timeZone: 'UTC' })
const signed = (v: string) => (v.startsWith('+') ? CH.pos : v.startsWith('−') || v.startsWith('-') ? CH.neg : C.text)

function Mark({ busy = false }: { busy?: boolean }) {
  return (
    <span style={{ width: 36, height: 36, flex: 'none', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: C.accent, color: C.onAccent }}>
      {busy ? <LoaderCircle size={18} className="animate-spin" /> : <Sparkles size={18} strokeWidth={2.2} />}
    </span>
  )
}

export function ResearchNote({ ticker, name }: { ticker: string; name: string }) {
  const { data, error } = useData(() => getNote(ticker).then((note) => ({ note })), ticker)
  const [written, setWritten] = useState<Note | null>(null)
  const [busy, setBusy] = useState(false)
  const [sources, setSources] = useState<NoteSources | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const note = written ?? data?.note ?? null

  const run = async (refresh = false) => {
    setBusy(true)
    setSources(null)
    setFailed(null)
    try {
      setSources(await gatherSources(ticker))
      setWritten(await writeNote(ticker, refresh))
    } catch (e) {
      setFailed(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (error) return <Card style={{ padding: 18, fontFamily: F.body, fontSize: 13.5, color: C.muted }}>{error}</Card>
  if (!data) return <Skeleton h={240} r={14} />
  if (busy) return <Writing name={name} sources={sources} />
  if (!note)
    return (
      <div style={{ ...frame, display: 'grid', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Mark />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: F.body, fontSize: 16, fontWeight: 650, color: C.text, letterSpacing: '-0.01em' }}>Research note on {name}</div>
            <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted, marginTop: 2 }}>Bull case, bear case and what to watch, from the latest 10-K, the financials and the news</div>
          </div>
        </div>
        <div>
          <button type="button" className="btn btn-primary" onClick={() => run()}>
            <Sparkles size={15} /> Write the note
          </button>
        </div>
        {failed && <span style={{ fontFamily: F.body, fontSize: 13, color: C.red }}>{failed}</span>}
      </div>
    )
  return <NoteView note={note} onRewrite={() => run(true)} failed={failed} />
}

/** Progress while a note is written: the sources once they're read, then the writing. */
function Writing({ name, sources }: { name: string; sources: NoteSources | null }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const read = sources
    ? [sources.tenk && `${sources.tenk} passages from the 10-K${sources.filed ? ` filed ${date(sources.filed)}` : ''}`, `${sources.facts} financial facts`, `${sources.news} news items`, `${sources.data} FinSight figures`].filter(Boolean).join(' · ')
    : null
  const step = (done: boolean, active: boolean, label: string, detail?: string | null) => (
    <li style={{ display: 'grid', gridTemplateColumns: '22px 1fr', gap: 10, alignItems: 'start' }}>
      <span style={{ width: 22, height: 22, borderRadius: 11, display: 'flex', alignItems: 'center', justifyContent: 'center', color: done ? C.onAccent : C.accent, background: done ? C.accent : C.accentSoft }}>
        {done ? <Check size={13} strokeWidth={3} /> : active ? <LoaderCircle size={13} className="animate-spin" /> : null}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontFamily: F.body, fontSize: 14, fontWeight: 600, color: done || active ? C.text : C.muted }}>{label}</div>
        {detail && <div style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, marginTop: 2 }}>{detail}</div>}
      </div>
    </li>
  )
  return (
    <div style={{ ...frame, display: 'grid', gap: 16 }} aria-live="polite">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Mark busy />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: F.body, fontSize: 16, fontWeight: 650, color: C.text, letterSpacing: '-0.01em' }}>Writing a research note on {name}</div>
          <div style={{ ...NUM, fontSize: 12.5, color: C.muted, marginTop: 2 }}>
            {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')}
          </div>
        </div>
      </div>
      <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 12 }}>
        {step(!!sources, !sources, sources ? 'Read the sources' : 'Reading the 10-K, financials and news', read)}
        {step(false, !!sources, 'Writing the note and checking every figure against its source')}
      </ol>
      <div style={{ display: 'grid', gap: 8 }}>
        <Skeleton h={18} w="70%" />
        <Skeleton h={10} />
        <Skeleton h={10} w="86%" />
      </div>
    </div>
  )
}

function citedIds(note: Note): Set<string> {
  const out = new Set<string>(note.key_facts)
  for (const text of [note.summary, ...[...note.bull, ...note.bear, ...note.watch].map((p) => p.text)])
    for (const m of text.matchAll(/\[([A-Z]\d+(?:\s*,\s*[A-Z]\d+)*)\]/g)) m[1].split(',').forEach((id) => out.add(id.trim()))
  return out
}

function NoteView({ note, onRewrite, failed }: { note: Note; onRewrite: () => void; failed: string | null }) {
  const byId = new Map(note.items.map((i) => [i.id, i]))
  const ids = new Set(byId.keys())
  const facts = note.key_facts.map((id) => byId.get(id)).filter((i): i is NoteItem => !!i)
  return (
    <Card style={{ overflow: 'hidden' }}>
      <div style={{ padding: 18, display: 'grid', gap: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Mark />
          <div style={{ minWidth: 0, flex: 1, fontFamily: F.body, fontSize: 13, color: C.muted }}>
            <span style={{ fontWeight: 600, color: C.text }}>AI research note</span> · {date(note.generated)}
          </div>
          {!DEMO && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={onRewrite} title="Write the note again from the latest sources">
              <RefreshCw size={14} /> Rewrite
            </button>
          )}
        </div>

        <div>
          <h2 style={{ fontFamily: F.display, fontSize: 21, fontWeight: 650, lineHeight: 1.3, letterSpacing: '-0.015em', color: C.text, margin: 0 }}>{note.headline}</h2>
          {note.summary && (
            <p style={{ fontFamily: F.body, fontSize: 14.5, lineHeight: 1.65, color: C.dim, margin: '10px 0 0' }}>
              <Cited text={note.summary} ids={ids} prefix={PREFIX} />
            </p>
          )}
        </div>

        {facts.length > 0 && (
          // A wrapping row: the last tile stretches to fill its row. Each tile draws its right and bottom divider inside
          // itself; the row overhangs the frame by a pixel so the outermost dividers are clipped.
          <div style={{ border: `1px solid ${C.rule}`, borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', marginRight: -1, marginBottom: -1 }}>
            {facts.map((f) => {
              const [label, period] = f.title.split(/, (?=FY)/)
              return (
                <a key={f.id} href={`#${PREFIX}-${f.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(`${PREFIX}-${f.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }} style={{ flex: '1 1 132px', background: C.surface, padding: '12px 14px', textDecoration: 'none', minWidth: 0, boxShadow: `inset -1px -1px 0 ${C.rule}` }}>
                  <SectionLabel>{label}</SectionLabel>
                  <div style={{ ...NUM, fontSize: 20, fontWeight: 650, letterSpacing: '-0.01em', color: signed(f.text), marginTop: 6 }}>{f.text}</div>
                  <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 2 }}>{period?.split(' ')[0]}</div>
                </a>
              )
            })}
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {note.bull.length > 0 && <Side title="Bull case" up points={note.bull} ids={ids} />}
          {note.bear.length > 0 && <Side title="Bear case" up={false} points={note.bear} ids={ids} />}
        </div>

        {note.watch.length > 0 && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <Eye size={16} color={C.accent} />
              <span style={{ fontFamily: F.body, fontSize: 15, fontWeight: 650, color: C.text }}>What to watch</span>
            </div>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 10 }}>
              {note.watch.map((p, i) => (
                <li key={i} style={{ fontFamily: F.body, fontSize: 13.5, lineHeight: 1.6, color: C.dim, paddingLeft: 14, borderLeft: `2px solid ${C.edge}` }}>
                  <span style={{ fontWeight: 600, color: C.text }}>{p.title}.</span> <Cited text={p.text} ids={ids} prefix={PREFIX} />
                </li>
              ))}
            </ul>
          </div>
        )}

        <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>AI-generated from the sources below. Check them before relying on it.</div>
        {failed && <span style={{ fontFamily: F.body, fontSize: 13, color: C.red }}>{failed}</span>}
      </div>
      <Sources items={note.items} cited={citedIds(note)} />
    </Card>
  )
}

function Side({ title, up, points, ids }: { title: string; up: boolean; points: NotePoint[]; ids: Set<string> }) {
  const color = up ? CH.pos : CH.neg
  const Icon = up ? ArrowUpRight : ArrowDownRight
  return (
    <section style={{ border: `1px solid ${C.rule}`, borderRadius: 12, padding: '14px 16px', borderTop: `3px solid ${color}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ width: 26, height: 26, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', color, background: `color-mix(in srgb, ${color} 12%, transparent)` }}>
          <Icon size={16} strokeWidth={2.4} />
        </span>
        <span style={{ fontFamily: F.body, fontSize: 15, fontWeight: 650, color: C.text }}>{title}</span>
      </div>
      <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 12 }}>
        {points.map((p, i) => (
          <li key={i} style={{ paddingTop: i ? 12 : 0, borderTop: i ? `1px solid ${C.rule}` : 'none' }}>
            <div style={{ fontFamily: F.body, fontSize: 14, fontWeight: 600, color: C.text }}>{p.title}</div>
            <div style={{ fontFamily: F.body, fontSize: 13.5, lineHeight: 1.6, color: C.dim, marginTop: 3 }}>
              <Cited text={p.text} ids={ids} prefix={PREFIX} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

const GROUPS: { kind: NoteItem['kind']; label: string }[] = [
  { kind: 'tenk', label: 'Annual report (10-K)' },
  { kind: 'fact', label: 'Financial statements' },
  { kind: 'news', label: 'News and filings' },
  { kind: 'data', label: 'FinSight data' },
]

function Sources({ items, cited }: { items: NoteItem[]; cited: Set<string> }) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.filter((i) => cited.has(i.id))
  return (
    <div style={{ borderTop: `1px solid ${C.rule}`, padding: '14px 18px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
        <PanelTitle>Sources</PanelTitle>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAll((a) => !a)}>
          {all ? `Show the ${cited.size} cited` : `Show all ${items.length}`}
        </button>
      </div>
      {GROUPS.map(({ kind, label }) => {
        const group = shown.filter((i) => i.kind === kind)
        if (group.length === 0) return null
        const filing = kind === 'tenk' ? group[0] : null
        return (
          <div key={kind} style={{ marginTop: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 10px', marginBottom: 2 }}>
              <SectionLabel>{label}</SectionLabel>
              {filing?.url && (
                <a href={filing.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: F.body, fontSize: 12, color: C.accent, textDecoration: 'none' }}>
                  filed {date(filing.meta.filed ?? '')} <ExternalLink size={11} />
                </a>
              )}
            </div>
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {group.map((i) => (
                <SourceRow key={i.id} item={i} />
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

function SourceRow({ item }: { item: NoteItem }) {
  const [open, setOpen] = useState(false)
  const value = item.kind === 'fact' || item.meta.value
  const passage = item.kind === 'tenk' && item.text
  const row: CSSProperties = { display: 'grid', gridTemplateColumns: '34px 1fr auto', alignItems: 'center', gap: 10, padding: '7px 10px', borderRadius: 8, width: '100%', textAlign: 'left', textDecoration: 'none', color: C.text, background: 'transparent', border: 'none', font: 'inherit', cursor: passage || item.url ? 'pointer' : 'default' }
  const body: ReactNode = (
    <>
      <span style={{ ...NUM, fontSize: 11, fontWeight: 600, color: C.muted }}>{item.id}</span>
      <span style={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        {item.kind === 'news' && item.meta.date && <span style={{ ...NUM, flex: 'none', fontSize: 12.5, color: C.muted }}>{date(item.meta.date, false)}</span>}
        {item.kind === 'tenk' && <span style={{ ...NUM, flex: 'none', fontSize: 11.5, color: C.muted }}>Item {item.meta.item}</span>}
        <span className="truncate" style={{ fontFamily: F.body, fontSize: 13.5 }}>
          {item.title}
        </span>
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 12, color: C.muted, whiteSpace: 'nowrap' }}>
        {value && <span style={{ ...NUM, fontSize: 13.5, fontWeight: 600, color: signed(item.text) }}>{item.text}</span>}
        {item.kind === 'news' && (
          <span className="hidden sm:inline" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {item.meta.source}
          </span>
        )}
        {item.kind === 'news' && <ExternalLink size={12} />}
        {passage && <ChevronDown size={14} style={{ transform: open ? 'rotate(180deg)' : undefined, transition: 'transform 150ms' }} />}
      </span>
    </>
  )
  return (
    <li id={`${PREFIX}-${item.id}`} style={{ borderRadius: 8 }}>
      {item.kind === 'news' && item.url ? (
        <a href={item.url} target="_blank" rel="noreferrer" className="hover-lift" style={row}>
          {body}
        </a>
      ) : passage ? (
        <button type="button" className="hover-lift" style={row} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {body}
        </button>
      ) : (
        <div style={row}>{body}</div>
      )}
      {open && passage && (
        <blockquote style={{ margin: '2px 10px 10px 54px', padding: '10px 14px', borderLeft: `2px solid ${C.edge}`, background: C.raised, borderRadius: 8, fontFamily: F.body, fontSize: 13, lineHeight: 1.6, color: C.dim }}>
          {item.text}
          {item.url && (
            <a href={item.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 8, color: C.accent, textDecoration: 'none', fontSize: 12.5 }}>
              Open the 10-K <ExternalLink size={11} />
            </a>
          )}
        </blockquote>
      )}
    </li>
  )
}
