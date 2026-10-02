import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { C, F, NUM } from '../design/tokens'
import type { Answer, Citation } from '../types'

interface Props {
  answer: Answer
  markdown: string
  selected: Citation | null
  onCite: (c: Citation) => void
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Turns the backend's plain answer into interactive Markdown:
 *   "[3M FY18 p.60; 3M FY18 p.61]"  ->  citation chips (#cite:<index>)
 *   "$1,577 million" (verified) / "14.86%" (computed)  ->  badges (#fig:<name> / #calc:<name>)
 */
function annotate(text: string, answer: Answer, cites: Citation[]): string {
  const marks: { display: string; href: string }[] = [
    ...answer.calculations.filter((c) => c.value !== null).map((c) => ({ display: c.display, href: `#calc:${c.name}` })),
    ...answer.figures.filter((f) => f.verified).map((f) => ({ display: f.display, href: `#fig:${f.name}` })),
  ]
    .filter((m) => m.display && m.display !== 'n/a')
    .sort((a, b) => b.display.length - a.display.length)

  const labelIndex = new Map<string, number>()
  cites.forEach((c, i) => {
    if (!labelIndex.has(c.label)) labelIndex.set(c.label, i)
  })

  // One pass over citation brackets and number displays so replacements never nest.
  const alts = [String.raw`\[([^\[\]]+ p\.\d+(?:;[^\[\]]+ p\.\d+)*)\]`, ...marks.map((m) => escape(m.display))]
  const re = new RegExp(alts.join('|'), 'g')
  return text.replace(re, (whole, citeGroup?: string) => {
    if (citeGroup) {
      return citeGroup
        .split(';')
        .map((label) => label.trim())
        .map((label) => {
          const i = labelIndex.get(label)
          return i === undefined ? label : ` [${label}](#cite:${i})`
        })
        .join('')
    }
    const m = marks.find((x) => x.display === whole)
    return m ? `[${whole}](${m.href})` : whole
  })
}

const badge = (color: string, soft: string) =>
  ({ ...NUM, fontWeight: 600, color, background: soft, borderRadius: 3, padding: '0 4px' }) as const

export function AnswerText({ answer, markdown, selected, onCite }: Props) {
  const cites = answer.citations.length ? answer.citations : answer.retrieved
  const md = annotate(markdown, answer, cites)

  return (
    <div className="answer" style={{ fontFamily: F.body, fontSize: 15, color: C.text }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children }) {
            if (href?.startsWith('#cite:')) {
              const c = cites[Number(href.slice(6))]
              if (!c) return <>{children}</>
              const active = selected?.doc_id === c.doc_id && selected?.page === c.page
              return (
                <button
                  type="button"
                  onClick={() => onCite(c)}
                  title={`${c.company} ${c.fiscal_label}, page ${c.page} · ${c.section}`}
                  className={active ? '' : 'hover-lift'}
                  style={{
                    fontFamily: F.mono,
                    fontSize: 10.5,
                    letterSpacing: '0.04em',
                    margin: '0 2px',
                    padding: '2px 6px',
                    borderRadius: 4,
                    verticalAlign: 'middle',
                    border: `1px solid ${active ? C.accent : C.edge}`,
                    background: active ? C.accent : C.surface,
                    color: active ? C.onAccent : C.accent,
                    cursor: 'pointer',
                  }}
                >
                  {children}
                </button>
              )
            }
            if (href?.startsWith('#fig:')) {
              const f = answer.figures.find((x) => x.name === href.slice(5))
              return (
                <span style={badge(C.verified, C.verifiedSoft)} title={f ? `Verified: printed in source ${f.source_id}` : 'Verified on the cited page'}>
                  {children}
                </span>
              )
            }
            if (href?.startsWith('#calc:')) {
              const c = answer.calculations.find((x) => x.name === href.slice(6))
              return (
                <span style={badge(C.computed, C.computedSoft)} title={c ? `Computed in Python: ${c.op}(${c.inputs.join(', ')})` : 'Computed in Python'}>
                  {children}
                </span>
              )
            }
            return (
              <a href={href} style={{ color: C.accent, textDecoration: 'underline' }} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  )
}
