// Text with [N1, K2] citations turned into chips that jump to the source row with the same id on the page.
import { Fragment } from 'react'
import { C, NUM } from '../design/tokens'

export function Cited({ text, ids, prefix = 'ev' }: { text: string; ids: Set<string>; prefix?: string }) {
  const parts = text.split(/(\[[A-Z]\d+(?:\s*,\s*[A-Z]\d+)*\])/g)
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^\[(.*)\]$/)
        if (!m) return <Fragment key={i}>{p}</Fragment>
        return (
          <Fragment key={i}>
            {m[1]
              .split(',')
              .map((s) => s.trim())
              .filter((s) => ids.has(s))
              .map((id) => (
                <Chip key={id} id={id} prefix={prefix} />
              ))}
          </Fragment>
        )
      })}
    </>
  )
}

export function Chip({ id, prefix = 'ev' }: { id: string; prefix?: string }) {
  return (
    <a
      href={`#${prefix}-${id}`}
      onClick={(e) => {
        e.preventDefault()
        const el = document.getElementById(`${prefix}-${id}`)
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el?.animate([{ background: 'var(--color-accent-soft)' }, { background: 'transparent' }], { duration: 1600 })
      }}
      style={{ ...NUM, display: 'inline-block', fontSize: 11, fontWeight: 600, color: C.accent, background: C.accentSoft, border: `1px solid ${C.edge}`, borderRadius: 5, padding: '0 5px', margin: '0 2px', textDecoration: 'none', verticalAlign: 'middle', lineHeight: '17px' }}
    >
      {id}
    </a>
  )
}
