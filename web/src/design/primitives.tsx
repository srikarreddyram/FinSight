// Core primitives (Shot Vision design system, FinSight colours). Every colour comes from tokens.
import type { CSSProperties, ReactNode } from 'react'
import { C, F, tierColor } from './tokens'

/** Quiet card; an accent is a left stripe, never a full fill, so saturated colour is reserved for what matters. */
export function Card({
  children,
  accent,
  style,
  className = '',
}: {
  children: ReactNode
  accent?: string
  style?: CSSProperties
  className?: string
}) {
  return (
    <div
      className={className}
      style={{
        background: C.surface,
        border: `1px solid ${C.rule}`,
        borderLeft: accent ? `3px solid ${accent}` : `1px solid ${C.rule}`,
        borderRadius: 8,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** The eyebrow: mono, small, wide tracking, accent colour. The one recurring "this labels the block below" style. */
export function SectionLabel({
  children,
  color = C.accent,
  style,
  className,
}: {
  children: ReactNode
  color?: string
  style?: CSSProperties
  className?: string
}) {
  return (
    <div
      className={className}
      style={{
        fontFamily: F.mono,
        fontSize: 10,
        color,
        letterSpacing: '0.32em',
        textTransform: 'uppercase',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** Two- or three-way toggle. The active option changes typeface as well as colour: readable from across a room. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
}: {
  options: { value: T; label: string; title?: string }[]
  value: T
  onChange: (v: T) => void
  disabled?: boolean
}) {
  return (
    <div
      role="group"
      style={{
        display: 'inline-flex',
        background: C.surface,
        border: `1px solid ${C.rule}`,
        borderRadius: 6,
        padding: 3,
        gap: 3,
      }}
    >
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            disabled={disabled}
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            title={o.title}
            style={{
              background: active ? C.accent : 'transparent',
              color: active ? C.onAccent : C.muted,
              border: 'none',
              borderRadius: 4,
              padding: active ? '4px 16px' : '6px 14px',
              cursor: disabled ? 'default' : 'pointer',
              fontFamily: active ? F.display : F.mono,
              fontWeight: active ? 600 : 400,
              fontSize: active ? 15 : 10,
              letterSpacing: active ? '0.06em' : '0.2em',
              textTransform: 'uppercase',
              transition: 'all 200ms',
              opacity: disabled ? 0.5 : 1,
            }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/** Score bar whose colour IS the data (tier ramp), growing in from zero. */
export function Bar({ pct, color, height = 4 }: { pct: number; color?: string; height?: number }) {
  return (
    <div style={{ flex: 1, height, background: C.rule, borderRadius: height / 2, overflow: 'hidden' }}>
      <div
        className="anim-bar"
        style={{
          width: `${Math.max(2, Math.min(1, pct) * 100)}%`,
          height: '100%',
          background: color ?? tierColor(pct),
          borderRadius: height / 2,
          transition: 'width 300ms',
        }}
      />
    </div>
  )
}

/** A big headline number: display face, pops into place. */
export function Stat({ label, value, color = C.text, note, delay = 0 }: { label: string; value: string; color?: string; note?: string; delay?: number }) {
  return (
    <div className="anim-stat-pop" style={{ animationDelay: `${delay}ms`, minWidth: 0 }}>
      <SectionLabel color={C.muted} style={{ letterSpacing: '0.22em' }}>
        {label}
      </SectionLabel>
      <div style={{ fontFamily: F.display, fontWeight: 600, fontSize: 34, lineHeight: 1.05, color, marginTop: 4, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      {note && <div style={{ fontFamily: F.mono, fontSize: 10.5, color: C.muted, marginTop: 3 }}>{note}</div>}
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: '44px 24px', textAlign: 'center', color: C.muted, fontFamily: F.mono, fontSize: 11, letterSpacing: '0.16em', lineHeight: 1.8 }}>
      {children}
    </div>
  )
}

/** Names what the person can actually check, not just "an error occurred". */
export function ErrorState({ title = 'The engine didn’t answer', message, hint }: { title?: string; message: string; hint?: string }) {
  return (
    <Card accent={C.red} style={{ padding: '16px 20px' }} className="anim-fade-up">
      <div style={{ fontFamily: F.body, fontWeight: 600, fontSize: 14, color: C.text }}>{title}</div>
      <div style={{ fontFamily: F.mono, fontSize: 11.5, color: C.muted, marginTop: 5, lineHeight: 1.6 }}>
        {message}
        {hint ? ` — ${hint}` : ''}
      </div>
    </Card>
  )
}

const skel = (w: number | string, h = 9, o = 1): CSSProperties => ({
  width: w,
  height: h,
  background: C.rule,
  borderRadius: 2,
  opacity: o,
  animation: 'shimmer 1.6s ease-in-out infinite',
})

/** Mirrors the real answer card: hero row (identity + three numbers), then prose lines fading downward. */
export function AnswerSkeleton() {
  return (
    <Card style={{ padding: 20 }}>
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <div style={skel(70, 8)} />
          <div style={{ ...skel(180, 22), marginTop: 8 }} />
        </div>
        {[0, 1, 2].map((i) => (
          <div key={i}>
            <div style={skel(60, 8)} />
            <div style={{ ...skel(90, 26), marginTop: 8 }} />
          </div>
        ))}
      </div>
      <div style={{ marginTop: 22, display: 'grid', gap: 10 }}>
        {[1, 0.94, 0.97, 0.7].map((w, i) => (
          <div key={i} style={skel(`${w * 100}%`, 10, 1 - i * 0.18)} />
        ))}
      </div>
    </Card>
  )
}

/** Mirrors a filing page: title block, a table grid, then text lines fading toward the bottom. */
export function PageSkeleton() {
  return (
    <div style={{ background: C.surface, borderRadius: 6, padding: '28px 32px', height: '100%', border: `1px solid ${C.rule}` }}>
      <div style={skel('38%', 10)} />
      <div style={{ ...skel('26%', 8), marginTop: 8 }} />
      <div style={{ marginTop: 24, display: 'grid', gap: 9 }}>
        {Array.from({ length: 14 }).map((_, i) => (
          <div key={i} style={{ display: 'flex', gap: 14, opacity: 1 - i * 0.045 }}>
            <div style={skel('46%', 7)} />
            <div style={{ flex: 1 }} />
            {[40, 40, 40].map((w, j) => (
              <div key={j} style={skel(w, 7)} />
            ))}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 26, display: 'grid', gap: 8 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={skel(`${92 - (i % 3) * 7}%`, 7, 0.7 - i * 0.09)} />
        ))}
      </div>
    </div>
  )
}
