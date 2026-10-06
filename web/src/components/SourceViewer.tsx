import { ChevronLeft, ChevronRight, ExternalLink, FileText } from 'lucide-react'
import { useState } from 'react'
import { pageImageUrl, pdfUrl } from '../api'
import { EmptyState, PageSkeleton, SectionLabel } from '../design/primitives'
import { C, F, NUM } from '../design/tokens'
import type { Citation } from '../types'

interface Props {
  citation: Citation | null
}

const navBtn = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 28,
  height: 28,
  borderRadius: 7,
  border: `1px solid ${C.rule}`,
  background: C.surface,
  color: C.dim,
  cursor: 'pointer',
} as const

export function SourceViewer({ citation }: Props) {
  // The parent remounts this component (key) per citation, so page starts at the cited page.
  const [page, setPage] = useState(citation?.page ?? 1)
  const [loaded, setLoaded] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  if (!citation) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <EmptyState>
          <FileText size={22} style={{ margin: '0 auto 8px', display: 'block' }} />
          <span style={{ fontWeight: 600, color: C.dim }}>Source viewer</span>
          <br />
          Click a citation to open the filing page it came from.
        </EmptyState>
      </div>
    )
  }

  const src = pageImageUrl(citation, page)
  const loading = loaded !== src && failed !== src
  const onCitedPage = page === citation.page
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '6px 12px',
          padding: '12px 16px',
          borderBottom: `1px solid ${C.rule}`,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <SectionLabel>Source</SectionLabel>
          <div
            style={{ fontFamily: F.display, fontWeight: 600, fontSize: 16, lineHeight: 1.3, marginTop: 4, color: C.text }}
            className="truncate"
          >
            {citation.company} · {citation.fiscal_label}
          </div>
          <div className="truncate" style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 2 }}>
            {citation.doc_id} · {citation.section}
            {citation.chunk_type === 'table' ? ' · table' : ''}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} style={navBtn} className="hover-lift" aria-label="Previous page">
            <ChevronLeft size={15} />
          </button>
          <span style={{ ...NUM, fontSize: 11.5, minWidth: 70, textAlign: 'center', color: C.text }}>
            p.{page}
            {onCitedPage ? '' : <span style={{ color: C.muted }}> · cited {citation.page}</span>}
          </span>
          <button type="button" onClick={() => setPage((p) => p + 1)} style={navBtn} className="hover-lift" aria-label="Next page">
            <ChevronRight size={15} />
          </button>
        </div>
        <a
          href={pdfUrl(citation.doc_id, page)}
          target="_blank"
          rel="noreferrer"
          className="btn btn-secondary btn-sm"
        >
          Open PDF <ExternalLink size={13} />
        </a>
      </div>

      <div style={{ position: 'relative', flex: 1, overflow: 'auto', background: C.bg, padding: 12 }}>
        {loading && (
          <div style={{ position: 'absolute', inset: 12 }} aria-label="Loading page">
            <PageSkeleton />
          </div>
        )}
        {failed === src ? (
          <div style={{ padding: 20, fontFamily: F.body, fontSize: 13, color: C.muted }}>
            The page image isn’t available (is the PDF downloaded?). Cited passage:
            <pre
              style={{
                marginTop: 12,
                whiteSpace: 'pre-wrap',
                ...NUM,
                fontSize: 11.5,
                color: C.text,
                background: C.surface,
                border: `1px solid ${C.rule}`,
                borderRadius: 6,
                padding: 12,
              }}
            >
              {citation.snippet}
            </pre>
          </div>
        ) : (
          <img
            key={`${citation.doc_id}-${page}-${citation.id}`}
            src={src}
            alt={`${citation.doc_id} page ${page}`}
            onLoad={() => setLoaded(src)}
            onError={() => setFailed(src)}
            className={loading ? '' : 'anim-fade-up'}
            style={{
              display: 'block',
              margin: '0 auto',
              width: '100%',
              maxWidth: 768,
              borderRadius: 6,
              border: `1px solid ${C.rule}`,
              background: '#fff', // the filing page itself is always paper-white
              opacity: loading ? 0 : 1,
            }}
          />
        )}
      </div>
      {onCitedPage && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            borderTop: `1px solid ${C.rule}`,
            padding: '8px 16px',
            fontFamily: F.body,
            fontSize: 12,
            color: C.muted,
          }}
        >
          <span style={{ width: 10, height: 10, borderRadius: 2, background: 'rgba(252, 211, 77, 0.8)' }} />
          Highlighted: the {citation.highlight ? 'rows the answer took its figures from' : 'start of the cited passage'}
        </div>
      )}
    </div>
  )
}
