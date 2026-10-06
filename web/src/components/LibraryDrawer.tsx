import { Upload, X } from 'lucide-react'
import { type CSSProperties, type FormEvent, useMemo, useState } from 'react'
import { ingest, type IngestReport } from '../api'
import { useEscape } from '../shell/useEscape'
import { Card, SectionLabel } from '../design/primitives'
import { C, F, NUM } from '../design/tokens'
import type { DocumentInfo } from '../types'

interface Props {
  open: boolean
  docs: DocumentInfo[]
  onClose: () => void
  onIngested: () => void
}

/** Indexed filings by company (CSS columns pack uneven cards), plus the upload form (PRD FR11). */
export function LibraryDrawer({ open, docs, onClose, onIngested }: Props) {
  const [filter, setFilter] = useState('')
  const groups = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const by = new Map<string, DocumentInfo[]>()
    for (const d of docs) {
      if (f && !`${d.company} ${d.ticker} ${d.doc_id}`.toLowerCase().includes(f)) continue
      by.set(d.company, [...(by.get(d.company) ?? []), d])
    }
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [docs, filter])

  useEscape(open, onClose)
  if (!open) return null
  const indexed = docs.filter((d) => d.indexed).length
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', justifyContent: 'flex-end' }} role="dialog" aria-modal="true" aria-label="Filing library">
      <button
        type="button"
        onClick={onClose}
        aria-label="Close library"
        style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.45)', border: 'none', cursor: 'pointer' }}
      />
      <aside
        className="anim-slide"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 760,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          background: C.bg,
          borderLeft: `1px solid ${C.rule}`,
        }}
      >
        <header style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', padding: '20px 20px 14px', borderBottom: `1px solid ${C.rule}` }}>
          <div>
            <SectionLabel>Library</SectionLabel>
            <div style={{ fontFamily: F.display, fontWeight: 650, fontSize: 20, lineHeight: 1.25, letterSpacing: '-0.01em', marginTop: 6, color: C.text }}>
              {indexed} filings · {new Set(docs.map((d) => d.company)).size} companies
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="btn btn-ghost btn-icon"
          >
            <X size={18} />
          </button>
        </header>
        <div style={{ padding: '12px 20px', borderBottom: `1px solid ${C.rule}` }}>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by company or ticker"
            className="control"
            style={{ width: '100%' }}
          />
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          <div style={{ columnWidth: 220, columnGap: 12 }}>
            {groups.map(([company, list]) => (
              <Card key={company} style={{ breakInside: 'avoid', marginBottom: 12, padding: '12px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontFamily: F.body, fontWeight: 600, fontSize: 14, color: C.text }}>{company}</span>
                  <span style={{ ...NUM, fontSize: 12, fontWeight: 600, color: C.accent }}>{list[0].ticker}</span>
                </div>
                <ul style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
                  {list
                    .sort((a, b) => a.period_end.localeCompare(b.period_end))
                    .map((d) => (
                      <li
                        key={d.doc_id}
                        title={`${d.doc_id} · period ends ${d.period_end}`}
                        style={{
                          fontFamily: F.body,
                          fontSize: 11.5,
                          padding: '1px 7px',
                          borderRadius: 5,
                          border: `1px ${d.indexed ? 'solid' : 'dashed'} ${C.rule}`,
                          color: d.indexed ? C.dim : C.muted,
                        }}
                      >
                        {d.doc_type} {d.fiscal_label}
                        {!d.indexed && ' · pending'}
                      </li>
                    ))}
                </ul>
              </Card>
            ))}
          </div>
        </div>
        <UploadForm onDone={onIngested} />
      </aside>
    </div>
  )
}

const field: CSSProperties = { width: '100%', minWidth: 0 }

function UploadForm({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const el = e.currentTarget // React clears currentTarget once the handler awaits
    const form = new FormData(el)
    setBusy(true)
    setMsg(null)
    try {
      const r: IngestReport = await ingest(form)
      setMsg({ ok: true, text: `Indexed ${r.doc_id}: ${r.chunks} chunks${r.total_s ? ` in ${r.total_s}s` : ''}.` })
      onDone()
      el.reset()
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} style={{ borderTop: `1px solid ${C.rule}`, background: C.surface, padding: '14px 20px 18px', display: 'grid', gap: 10 }}>
      <SectionLabel>Add a filing</SectionLabel>
      <input name="file" type="file" accept="application/pdf" required style={{ fontFamily: F.body, fontSize: 12.5, color: C.dim }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        <input name="ticker" required placeholder="Ticker" className="control" style={field} />
        <input name="company" required placeholder="Company" className="control" style={field} />
        <select name="doc_type" defaultValue="annual_report" className="control" style={field}>
          <option value="annual_report">Annual report</option>
          <option value="10-K">10-K</option>
          <option value="10-Q">10-Q</option>
          <option value="20-F">20-F</option>
          <option value="earnings_call">Earnings call</option>
        </select>
        <input name="fiscal_year" type="number" required defaultValue={2025} aria-label="Fiscal year (year it ends)" className="control" style={field} />
        <select name="period" defaultValue="FY" className="control" style={field}>
          {['FY', 'Q1', 'Q2', 'Q3', 'Q4'].map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
        <input name="fiscal_year_end_month" type="number" min={1} max={12} defaultValue={3} aria-label="Fiscal year end month" className="control" style={field} />
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.body, fontSize: 12.5, color: C.muted }}>
        <input type="checkbox" name="parser" value="docling" /> Accurate tables (Docling, a few minutes)
      </label>
      <button
        type="submit"
        disabled={busy}
        className="btn btn-primary"
      >
        <Upload size={15} />
        {busy ? 'Parsing and indexing…' : 'Upload and index'}
      </button>
      {msg && <p style={{ fontFamily: F.body, fontSize: 12.5, color: msg.ok ? C.verified : C.warn }}>{msg.text}</p>}
    </form>
  )
}
