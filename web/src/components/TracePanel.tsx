import { type ReactNode, useState } from 'react'
import { Bar, Card, SectionLabel } from '../design/primitives'
import { C, F, NUM, tierColor } from '../design/tokens'
import type { Answer, Citation } from '../types'

interface Props {
  answer: Answer
  onCite: (c: Citation) => void
}

/** "How this answer was built": filters, evidence, Python checks, and cost. */
export function TracePanel({ answer, onCite }: Props) {
  const [open, setOpen] = useState(false)
  const pq = answer.parsed_query
  const t = answer.timings
  const u = answer.usage

  return (
    <Card className="anim-fade-up" style={{ animationDelay: '120ms' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          color: C.text,
        }}
      >
        <SectionLabel color={C.dim}>How this answer was built</SectionLabel>
        <span style={{ ...NUM, fontSize: 11, color: C.muted, display: 'flex', gap: 14, alignItems: 'center' }}>
          <span>{(t.total_s ?? 0).toFixed(1)}s</span>
          <span>{u.calls ?? 0} LLM calls</span>
          <span style={{ transition: 'transform 200ms', transform: open ? 'rotate(180deg)' : 'none' }}>⌄</span>
        </span>
      </button>

      {open && (
        <div style={{ borderTop: `1px solid ${C.rule}`, padding: '16px 16px 12px', display: 'grid', gap: 20 }}>
          {pq && (
            <Step n="01" title="Understood the question">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {pq.tickers.length === 0 && <Tag muted>no company detected · searched all filings</Tag>}
                {pq.tickers.map((tk) => (
                  <Tag key={tk}>
                    {tk}
                    {pq.fiscal_years[tk]?.length ? ` · FY${pq.fiscal_years[tk].map((y) => String(y).slice(2)).join(', FY')}` : ''}
                  </Tag>
                ))}
                {pq.sections.map((s) => (
                  <Tag key={s} muted>
                    boost · {s}
                  </Tag>
                ))}
                {pq.is_comparison && <Tag>comparison · one search per company</Tag>}
              </div>
            </Step>
          )}

          <Step n="02" title="Retrieved and reranked evidence">
            <ol style={{ display: 'grid', gap: 2 }}>
              {answer.retrieved.map((c, i) => (
                <li key={`${c.doc_id}-${c.page}-${i}`}>
                  <button
                    type="button"
                    onClick={() => onCite(c)}
                    className="hover-lift"
                    style={{
                      width: '100%',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '6px 8px',
                      background: 'transparent',
                      border: '1px solid transparent',
                      borderRadius: 5,
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                  >
                    <span style={{ ...NUM, fontSize: 10.5, color: C.muted, width: 18 }}>{String(i + 1).padStart(2, '0')}</span>
                    <span className="truncate" style={{ flex: 1, minWidth: 0, fontFamily: F.body, fontSize: 13, color: C.text }}>
                      {c.label} <span style={{ color: C.muted }}>· {c.section}</span>
                      {c.chunk_type === 'table' && (
                        <span style={{ fontFamily: F.mono, fontSize: 9, letterSpacing: '0.18em', color: C.muted, marginLeft: 6 }}>TABLE</span>
                      )}
                    </span>
                    {c.score !== null && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8, width: 110 }} title={`Reranker relevance ${c.score.toFixed(3)}`}>
                        <Bar pct={c.score} />
                        <span style={{ ...NUM, fontSize: 10.5, width: 30, textAlign: 'right', color: tierColor(c.score) }}>
                          {c.score.toFixed(2)}
                        </span>
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ol>
          </Step>

          {(answer.figures.length > 0 || answer.calculations.length > 0) && (
            <Step n="03" title="Numbers checked in Python">
              <table style={{ width: '100%', ...NUM, fontSize: 11.5, borderCollapse: 'collapse' }}>
                <tbody>
                  {answer.figures.map((f) => (
                    <Row key={f.name} name={f.name} value={f.display}>
                      {f.verified ? (
                        <span style={{ color: C.verified }}>✓ printed in {f.source_id}</span>
                      ) : (
                        <span style={{ color: C.warn }}>✗ not in source · dropped</span>
                      )}
                    </Row>
                  ))}
                  {answer.calculations.map((c) => (
                    <Row key={c.name} name={c.name} value={c.display}>
                      {c.value !== null ? (
                        <span style={{ color: C.computed }}>
                          = {c.op}({c.inputs.join(', ')})
                        </span>
                      ) : (
                        <span style={{ color: C.warn }}>✗ {c.error}</span>
                      )}
                    </Row>
                  ))}
                </tbody>
              </table>
            </Step>
          )}

          {answer.stripped_sentences.length > 0 && (
            <Step n="04" title="Removed for lack of evidence">
              <ul style={{ display: 'grid', gap: 6 }}>
                {answer.stripped_sentences.map((s, i) => (
                  <li
                    key={i}
                    style={{
                      fontFamily: F.mono,
                      fontSize: 11,
                      lineHeight: 1.5,
                      color: C.warn,
                      background: C.warnSoft,
                      borderRadius: 5,
                      padding: '6px 10px',
                    }}
                  >
                    {s}
                  </li>
                ))}
              </ul>
            </Step>
          )}

          <div
            style={{
              ...NUM,
              fontSize: 10.5,
              color: C.muted,
              display: 'flex',
              flexWrap: 'wrap',
              gap: '4px 18px',
              borderTop: `1px solid ${C.rule}`,
              paddingTop: 10,
            }}
          >
            <span>retrieval {(t.retrieve_s ?? 0).toFixed(2)}s</span>
            <span>total {(t.total_s ?? 0).toFixed(2)}s</span>
            <span>
              {(u.input_tokens ?? 0).toLocaleString()} in / {(u.output_tokens ?? 0).toLocaleString()} out tokens
            </span>
          </div>
        </div>
      )}
    </Card>
  )
}

function Step({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <section>
      <SectionLabel style={{ marginBottom: 8 }}>
        <span style={{ color: C.muted }}>{n}</span> · {title}
      </SectionLabel>
      {children}
    </section>
  )
}

function Row({ name, value, children }: { name: string; value: string; children: ReactNode }) {
  return (
    <tr style={{ borderBottom: `1px solid ${C.rule}` }}>
      <td style={{ padding: '6px 8px 6px 0', color: C.muted }}>{name}</td>
      <td style={{ padding: '6px 8px', textAlign: 'right', color: C.text }}>{value}</td>
      <td style={{ padding: '6px 0', textAlign: 'right' }}>{children}</td>
    </tr>
  )
}

function Tag({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  return (
    <span
      style={{
        fontFamily: F.mono,
        fontSize: 10.5,
        letterSpacing: '0.04em',
        borderRadius: 999,
        padding: '3px 10px',
        border: `1px solid ${muted ? C.rule : C.edge}`,
        background: muted ? 'transparent' : C.accentSoft,
        color: muted ? C.muted : C.accent,
      }}
    >
      {children}
    </span>
  )
}
