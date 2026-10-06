// The Copilot's opening screen: the ask box, example questions and recent questions. It turns into the workspace
// as soon as a question is asked.
import { History } from 'lucide-react'
import { C, F } from '../design/tokens'
import { AskBar } from './AskBar'

interface Props {
  busy: boolean
  history: string[]
  filings: number
  companies: number
  onAsk: (q: string) => void
}

export function Intro({ busy, history, filings, companies, onAsk }: Props) {
  return (
    <div className="anim-fade-up" style={{ maxWidth: 780, margin: '0 auto', padding: 'clamp(16px, 6vh, 64px) 0 24px' }}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: F.body, fontSize: 12.5, fontWeight: 500, color: C.accent, background: C.accentSoft, border: `1px solid ${C.edge}`, borderRadius: 999, padding: '3px 10px' }}>
        Filings Copilot
      </div>
      <h1 style={{ fontFamily: F.display, fontWeight: 650, fontSize: 'clamp(30px, 4.4vw, 42px)', lineHeight: 1.12, letterSpacing: '-0.022em', margin: '14px 0 0', color: C.text }}>
        Ask anything about a company’s filings
      </h1>
      <p style={{ fontFamily: F.body, fontSize: 16, lineHeight: 1.6, color: C.muted, margin: '12px 0 24px', maxWidth: 640 }}>
        Search {filings ? `${filings} filings from ${companies} companies` : 'indexed 10-Ks, 10-Qs and earnings calls'}, with answers cited to the page.
      </p>

      <AskBar busy={busy} onAsk={onAsk} />

      {history.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: C.muted }}>
            <History size={13} /> Recent questions
          </div>
          <ul style={{ marginTop: 6, display: 'grid', gap: 2 }}>
            {history.slice(0, 5).map((h) => (
              <li key={h}>
                <button
                  type="button"
                  onClick={() => onAsk(h)}
                  className="hover-lift truncate"
                  style={{ width: '100%', textAlign: 'left', background: 'transparent', border: '1px solid transparent', borderRadius: 8, padding: '7px 10px', fontFamily: F.body, fontSize: 14, color: C.dim, cursor: 'pointer' }}
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
