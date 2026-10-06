import { RotateCcw } from 'lucide-react'
import { Card, SectionLabel, Stat } from '../design/primitives'
import { C, F } from '../design/tokens'
import type { Answer, Citation } from '../types'
import { AnswerText } from './AnswerText'

interface Props {
  answer: Answer
  selected: Citation | null
  onCite: (c: Citation) => void
  onRetry?: () => void
}

const NOT_FOUND = 'Not found in the filings.'
const humanize = (name: string) => name.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()

export function AnswerCard(props: Props) {
  const { answer } = props
  if (answer.error) return <Failure {...props} />
  if (answer.refused) return <Refusal {...props} />
  return <Result {...props} />
}

/** Identity once at the top (company, filings), headline numbers beside it; detail below. */
function Result({ answer, selected, onCite }: Props) {
  const companies = [...new Set(answer.citations.map((c) => c.company))]
  const filings = [...new Set(answer.citations.map((c) => `${c.fiscal_label}`))]
  const headline = [
    ...answer.calculations.filter((c) => c.value !== null).map((c) => ({ label: humanize(c.name), value: c.display, color: C.computed, note: `computed · ${c.op}` })),
    ...answer.figures.filter((f) => f.verified).map((f) => ({ label: humanize(f.name), value: f.display, color: C.verified, note: `verified · ${f.source_id}` })),
  ].slice(0, 3)
  const verified = answer.figures.filter((f) => f.verified).length
  const computed = answer.calculations.filter((c) => c.value !== null).length
  const body = answer.answer + (answer.table_markdown ? `\n\n${answer.table_markdown}` : '')

  return (
    <Card className="anim-fade-up" style={{ overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '16px 28px',
          alignItems: 'flex-end',
          padding: '18px 20px',
          borderBottom: `1px solid ${C.rule}`,
          background: C.raised,
        }}
      >
        <div style={{ flex: '1 1 180px', minWidth: 0 }}>
          <SectionLabel>Answer</SectionLabel>
          <div style={{ fontFamily: F.display, fontWeight: 650, fontSize: 20, lineHeight: 1.25, letterSpacing: '-0.01em', marginTop: 6, color: C.text }}>
            {companies.join(' · ') || 'Filings'}
          </div>
          <div style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, marginTop: 3 }}>
            {filings.join(' · ')}
          </div>
        </div>
        {headline.map((h, i) => (
          <Stat key={h.label + i} label={h.label} value={h.value} color={h.color} note={h.note} delay={i * 90} />
        ))}
      </div>

      <div style={{ padding: '18px 20px 6px' }}>
        <AnswerText answer={answer} markdown={body} selected={selected} onCite={onCite} />
      </div>

      <footer
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '6px 18px',
          padding: '10px 20px 12px',
          borderTop: `1px solid ${C.rule}`,
          fontFamily: F.body,
          fontSize: 12,
          color: C.muted,
        }}
      >
        <span>
          {answer.citations.length} source{answer.citations.length === 1 ? '' : 's'} cited
        </span>
        {verified > 0 && <Legend color={C.verified} text={`${verified} verified on the page`} />}
        {computed > 0 && <Legend color={C.computed} text={`${computed} computed in Python`} />}
        {answer.stripped_sentences.length > 0 && (
          <span style={{ color: C.warn }}>{answer.stripped_sentences.length} unsupported sentence(s) removed</span>
        )}
      </footer>
    </Card>
  )
}

function Legend({ color, text }: { color: string; text: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
      {text}
    </span>
  )
}

/** A refusal is a feature: say so plainly and show the evidence that fell short. */
function Refusal({ answer, selected, onCite }: Props) {
  const note = answer.answer.replace(NOT_FOUND, '').replace('The closest passages are listed below.', '').trim()
  return (
    <Card accent={C.warn} className="anim-fade-up" style={{ padding: '18px 20px' }}>
      <SectionLabel color={C.warn}>Not found in the filings</SectionLabel>
      <p style={{ fontFamily: F.body, fontSize: 14, color: C.dim, marginTop: 8, lineHeight: 1.6 }}>
        {note || 'The indexed filings don’t cover this question.'}
      </p>
      <Passages list={answer.closest} selected={selected} onCite={onCite} />
    </Card>
  )
}

/** The model failed, not the evidence: name the likely cause and offer a retry. */
function Failure({ answer, selected, onCite, onRetry }: Props) {
  return (
    <Card accent={C.red} className="anim-fade-up" style={{ padding: '18px 20px' }}>
      <div style={{ fontFamily: F.body, fontWeight: 600, fontSize: 15, color: C.text }}>Couldn’t finish this answer</div>
      <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted, marginTop: 6, lineHeight: 1.6, wordBreak: 'break-word' }}>
        The service is busy. The closest passages are below; try again in a moment.
      </div>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn btn-primary" style={{ marginTop: 12 }}>
          <RotateCcw size={14} /> Try again
        </button>
      )}
      <Passages list={answer.retrieved.slice(0, 3)} selected={selected} onCite={onCite} />
    </Card>
  )
}

function Passages({ list, selected, onCite }: { list: Citation[]; selected: Citation | null; onCite: (c: Citation) => void }) {
  if (!list.length) return null
  return (
    <div style={{ marginTop: 16 }}>
      <SectionLabel color={C.muted}>Closest passages</SectionLabel>
      <ul style={{ display: 'grid', gap: 8, marginTop: 8 }}>
        {list.map((c) => {
          const active = selected?.doc_id === c.doc_id && selected?.page === c.page
          return (
            <li key={`${c.doc_id}-${c.page}-${c.id}`}>
              <button
                type="button"
                onClick={() => onCite(c)}
                className="hover-lift"
                style={{
                  width: '100%',
                  textAlign: 'left',
                  background: C.surface,
                  border: `1px solid ${active ? C.accent : C.rule}`,
                  borderRadius: 6,
                  padding: '10px 12px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontFamily: F.body, fontSize: 12, fontWeight: 600, color: C.accent }}>
                  {c.label} · {c.section}
                </div>
                <p className="line-clamp-2" style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, marginTop: 4 }}>
                  {c.snippet.replace(/[|#]/g, ' ').replace(/-{3,}/g, ' ')}
                </p>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
