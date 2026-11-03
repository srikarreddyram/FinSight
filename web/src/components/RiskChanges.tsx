// "10-K changes" on a company page: this year's Risk Factors against last year's, paragraph by paragraph. New
// risks in green, reworded ones with the words added and removed marked, dropped ones listed at the end.
import { ChevronDown, ExternalLink, FilePlus2, FileMinus2, FilePen } from 'lucide-react'
import { Fragment, useState, type ReactNode } from 'react'
import { Card, Segmented, Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { useData } from '../pages/data'
import { getChanges } from '../research/api'
import type { ChangeBlock } from '../research/types'

const AMBER = 'var(--grade-3)'
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
const STYLE = {
  new: { color: CH.pos, label: 'New', Icon: FilePlus2 },
  changed: { color: AMBER, label: 'Reworded', Icon: FilePen },
  removed: { color: CH.neg, label: 'Removed', Icon: FileMinus2 },
}

export function RiskChanges({ ticker }: { ticker: string }) {
  const { data, error } = useData(() => getChanges(ticker), ticker)
  const [show, setShow] = useState<'changes' | 'all'>('changes')
  if (error) return <Card style={{ padding: 18, fontFamily: F.body, fontSize: 13.5, color: C.muted }}>{error}</Card>
  if (!data) return <Skeleton h={320} r={14} />
  const { summary: s } = data
  const wordChange = data.current.words / data.previous.words - 1

  // Unchanged paragraphs collapse into one row per run, so the changes stand out.
  const items: ReactNode[] = []
  let run: ChangeBlock[] = []
  const flush = (key: string) => {
    if (run.length) items.push(<SameRun key={key} blocks={run} expanded={show === 'all'} />)
    run = []
  }
  data.blocks.forEach((b, i) => {
    if (b.status === 'same') run.push(b)
    else {
      flush(`same-${i}`)
      items.push(<Block key={i} b={b} />)
    }
  })
  flush('same-end')

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <Card style={{ padding: '16px 18px', display: 'grid', gap: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'baseline' }}>
          <div style={{ flex: '1 1 360px', minWidth: 0 }}>
            <div style={{ fontFamily: F.display, fontSize: 18, fontWeight: 650, color: C.text }}>Risk Factors, year over year</div>
            <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted, marginTop: 3 }}>
              <a href={data.current.url} target="_blank" rel="noreferrer" style={{ color: C.accent, textDecoration: 'none', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                10-K filed {day(data.current.filed)} <ExternalLink size={11} />
              </a>{' '}
              against{' '}
              <a href={data.previous.url} target="_blank" rel="noreferrer" style={{ color: C.accent, textDecoration: 'none', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {day(data.previous.filed)} <ExternalLink size={11} />
              </a>
            </div>
          </div>
          <Segmented
            size="sm"
            value={show}
            onChange={setShow}
            options={[
              { value: 'changes', label: 'Changes' },
              { value: 'all', label: 'Full text' },
            ]}
          />
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <Count color={CH.pos} label="New" n={s.new} />
          <Count color={AMBER} label="Reworded" n={s.changed} />
          <Count color={CH.neg} label="Removed" n={s.removed} />
          <Count color={C.muted} label="Unchanged" n={s.same} />
          <div style={{ borderRadius: 10, border: `1px solid ${C.rule}`, padding: '10px 12px' }}>
            <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>Length</div>
            <div style={{ ...NUM, fontSize: 18, fontWeight: 650, color: C.text, marginTop: 2 }}>{data.current.words.toLocaleString()}</div>
            <div style={{ ...NUM, fontSize: 11.5, color: C.muted }}>
              words, {wordChange >= 0 ? '+' : '−'}
              {Math.abs(wordChange * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </Card>

      <div style={{ display: 'grid', gap: 8 }}>{items}</div>

      {data.removed.length > 0 && (
        <>
          <h3 style={{ fontFamily: F.display, fontSize: 16, fontWeight: 650, color: C.text, margin: '8px 2px 0' }}>Dropped since last year</h3>
          <div style={{ display: 'grid', gap: 8 }}>
            {data.removed.map((b, i) => (
              <Block key={i} b={b} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function Count({ color, label, n }: { color: string; label: string; n: number }) {
  return (
    <div style={{ borderRadius: 10, border: `1px solid color-mix(in srgb, ${color} 35%, ${C.rule})`, background: `color-mix(in srgb, ${color} 8%, transparent)`, padding: '10px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 12, color: C.muted }}>
        <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} /> {label}
      </div>
      <div style={{ ...NUM, fontSize: 22, fontWeight: 650, color: C.text, marginTop: 2 }}>{n}</div>
    </div>
  )
}

function Block({ b }: { b: ChangeBlock }) {
  const st = STYLE[b.status as keyof typeof STYLE]
  return (
    <Card style={{ padding: '12px 16px 13px', borderLeft: `3px solid ${st.color}`, display: 'grid', gap: 6 }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.body, fontSize: 11.5, fontWeight: 650, letterSpacing: '0.03em', textTransform: 'uppercase', color: st.color }}>
        <st.Icon size={13} /> {st.label}
      </span>
      <p style={{ margin: 0, fontFamily: F.body, fontSize: b.heading ? 14.5 : 13.5, fontWeight: b.heading ? 600 : 400, lineHeight: 1.6, color: b.status === 'removed' ? C.dim : C.text, textDecoration: b.status === 'removed' ? 'line-through' : undefined, textDecorationColor: `color-mix(in srgb, ${CH.neg} 50%, transparent)` }}>
        {b.segments
          ? b.segments.map(([op, text], i) => (
              <Fragment key={i}>
                {op === '=' ? (
                  text
                ) : op === '+' ? (
                  <mark style={{ background: `color-mix(in srgb, ${CH.pos} 18%, transparent)`, color: C.text, borderRadius: 3, padding: '0 2px' }}>{text}</mark>
                ) : (
                  <del style={{ color: CH.neg, textDecorationColor: CH.neg, background: `color-mix(in srgb, ${CH.neg} 9%, transparent)`, borderRadius: 3, padding: '0 2px' }}>{text}</del>
                )}{' '}
              </Fragment>
            ))
          : b.text}
      </p>
    </Card>
  )
}

function SameRun({ blocks, expanded }: { blocks: ChangeBlock[]; expanded: boolean }) {
  const [open, setOpen] = useState(false)
  if (expanded || open)
    return (
      <div style={{ display: 'grid', gap: 6, padding: '4px 16px' }}>
        {blocks.map((b, i) => (
          <p key={i} style={{ margin: 0, fontFamily: F.body, fontSize: b.heading ? 14 : 13, fontWeight: b.heading ? 600 : 400, lineHeight: 1.6, color: C.dim }}>
            {b.text}
          </p>
        ))}
      </div>
    )
  return (
    <button type="button" onClick={() => setOpen(true)} className="hover-lift" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px', border: `1px dashed ${C.rule}`, borderRadius: 10, background: 'transparent', color: C.muted, fontFamily: F.body, fontSize: 12.5, cursor: 'pointer', textAlign: 'left' }}>
      <ChevronDown size={14} /> {blocks.length} unchanged paragraph{blocks.length === 1 ? '' : 's'}
    </button>
  )
}
