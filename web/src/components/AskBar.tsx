import { ArrowUp, LoaderCircle } from 'lucide-react'
import { type CSSProperties, useEffect, useRef, useState } from 'react'
import { C, F } from '../design/tokens'
import { EXAMPLES } from '../examples'

interface Props {
  busy: boolean
  initial?: string
  onAsk: (q: string) => void
  showExamples?: boolean
}

export function AskBar({ busy, initial = '', onAsk, showExamples = true }: Props) {
  const [q, setQ] = useState(initial)
  const [focused, setFocused] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)

  // "/" focuses the question box, like most search UIs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault()
        ref.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = () => {
    const text = q.trim()
    if (text && !busy) onAsk(text)
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 8,
          background: C.surface,
          border: `1px solid ${focused ? C.accent : C.rule}`,
          borderRadius: 12,
          padding: 7,
          transition: 'border-color 150ms, box-shadow 150ms',
          boxShadow: focused ? `0 0 0 3px ${C.hover}` : 'var(--shadow-card)',
          animation: busy ? 'accentPulse 1.8s ease infinite' : undefined,
        }}
      >
        <textarea
          ref={ref}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          rows={1}
          placeholder="Ask about revenue, margins, risk factors, liquidity…"
          aria-label="Question"
          style={
            {
              fieldSizing: 'content',
              flex: 1,
              minHeight: 40,
              maxHeight: 160,
              resize: 'none',
              background: 'transparent',
              border: 'none',
              outline: 'none',
              padding: '8px 8px',
              fontFamily: F.body,
              fontSize: 15,
              lineHeight: 1.5,
              color: C.text,
            } as CSSProperties
          }
        />
        <span aria-hidden className="kbd hidden sm:inline" style={{ alignSelf: 'center', marginRight: 2 }}>
          {focused ? '↵' : '/'}
        </span>
        <button type="button" onClick={submit} disabled={busy || !q.trim()} className="btn btn-primary" style={{ height: 40, flexShrink: 0, borderRadius: 9, padding: '0 14px', fontWeight: 600 }}>
          {busy ? <LoaderCircle size={16} className="animate-spin" /> : <ArrowUp size={16} strokeWidth={2.4} />}
          {busy ? 'Reading…' : 'Ask'}
        </button>
      </div>
      {showExamples && (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <span style={{ fontFamily: F.body, fontSize: 12.5, color: C.muted, marginRight: 2 }}>Try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              disabled={busy}
              onClick={() => {
                setQ(ex)
                onAsk(ex)
              }}
              className="hover-lift"
              title={ex}
              style={{
                fontFamily: F.body,
                fontSize: 12.5,
                color: C.dim,
                background: C.surface,
                border: `1px solid ${C.rule}`,
                borderRadius: 999,
                padding: '5px 12px',
                cursor: busy ? 'default' : 'pointer',
                opacity: busy ? 0.5 : 1,
              }}
            >
              {ex.length > 54 ? `${ex.slice(0, 52)}…` : ex}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
