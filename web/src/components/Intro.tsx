// The opening screen: a short, one-viewport landing (headline, pitch, ask bar, proof points) that
// turns into the workspace as soon as a question is asked.
import { Card, SectionLabel, Stat } from '../design/primitives'
import { C, F } from '../design/tokens'
import { AskBar } from './AskBar'

interface Props {
  busy: boolean
  history: string[]
  onAsk: (q: string) => void
}

const STATS = [
  { value: '84', label: 'SEC filings' },
  { value: '7,090', label: 'tables parsed' },
  { value: '83%', label: 'recall@10 · FinanceBench' },
]

const POINTS = [
  { title: 'Cited to the page', body: 'Every claim links to the filing page, with the rows it came from highlighted.', color: C.accent },
  { title: 'Numbers verified', body: 'Figures must be printed on the cited page; growth and ratios are computed in Python.', color: C.verified },
  { title: 'Refuses to guess', body: 'If the filings don’t say, you get “Not found” and the closest passages instead.', color: C.warn },
]

export function Intro({ busy, history, onAsk }: Props) {
  return (
    <div style={{ maxWidth: 820, margin: '0 auto', padding: 'clamp(24px, 7vh, 72px) 0 24px' }}>
      <SectionLabel className="anim-fade-up">Financial filings copilot</SectionLabel>
      <h1
        style={{
          fontFamily: F.display,
          fontWeight: 700,
          fontSize: 'clamp(48px, 9vw, 96px)',
          lineHeight: 0.95,
          margin: '10px 0 0',
          textTransform: 'uppercase',
          color: C.text,
        }}
      >
        {'Ask the filings.'.split(' ').map((w, i) => (
          <span key={i} className="anim-word" style={{ animationDelay: `${i * 0.09}s`, marginRight: '0.2em' }}>
            {w}
          </span>
        ))}
      </h1>
      <p className="anim-fade-up" style={{ animationDelay: '280ms', fontFamily: F.body, fontSize: 17, lineHeight: 1.6, color: C.dim, margin: '14px 0 26px', maxWidth: 620 }}>
        Answers from 10-Ks, 10-Qs and earnings calls, with every claim cited to a page and every number checked against it.
      </p>

      <div className="anim-fade-up" style={{ animationDelay: '380ms' }}>
        <AskBar busy={busy} onAsk={onAsk} />
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '18px 48px', marginTop: 36 }}>
        {STATS.map((s, i) => (
          <Stat key={s.label} label={s.label} value={s.value} color={C.accent} delay={500 + i * 110} />
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginTop: 30 }}>
        {POINTS.map((p, i) => (
          <Card key={p.title} accent={p.color} className="anim-fade-up" style={{ animationDelay: `${760 + i * 110}ms`, padding: '14px 16px' }}>
            <div style={{ fontFamily: F.display, fontWeight: 600, fontSize: 19, color: C.text, textTransform: 'uppercase', letterSpacing: '0.02em' }}>
              {p.title}
            </div>
            <p style={{ fontFamily: F.body, fontSize: 13, lineHeight: 1.55, color: C.muted, marginTop: 4 }}>{p.body}</p>
          </Card>
        ))}
      </div>

      {history.length > 0 && (
        <div className="anim-fade-up" style={{ animationDelay: '1000ms', marginTop: 32 }}>
          <SectionLabel color={C.muted}>Recent</SectionLabel>
          <ul style={{ marginTop: 8, display: 'grid', gap: 2 }}>
            {history.slice(0, 5).map((h) => (
              <li key={h}>
                <button
                  type="button"
                  onClick={() => onAsk(h)}
                  className="hover-lift truncate"
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    background: 'transparent',
                    border: '1px solid transparent',
                    borderRadius: 6,
                    padding: '7px 10px',
                    fontFamily: F.body,
                    fontSize: 14,
                    color: C.dim,
                    cursor: 'pointer',
                  }}
                >
                  {h}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
