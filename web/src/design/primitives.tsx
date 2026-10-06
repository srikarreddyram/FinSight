// Core primitives. Every colour comes from tokens; layout-level styles that need :hover live in index.css.
import type { CSSProperties, ReactNode } from 'react'
import { C, F, tierColor } from './tokens'

/** The standard surface: white (or dark card) on the page background, hairline border, faint shadow.
 *  An accent is a left stripe, never a fill, so saturated colour stays reserved for what matters. */
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
        borderRadius: 10,
        boxShadow: 'var(--shadow-card)',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** Small uppercase label above a value or a group ("Return rank", "Risk grade"). */
export function SectionLabel({
  children,
  color = C.muted,
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
        fontFamily: F.body,
        fontSize: 11.5,
        fontWeight: 600,
        color,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/** A panel's title: what the block below is about. Optional description under it. */
export function PanelTitle({ children, description, style }: { children: ReactNode; description?: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{ minWidth: 0, ...style }}>
      <h2 style={{ fontFamily: F.body, fontSize: 14.5, fontWeight: 600, color: C.text, margin: 0, lineHeight: 1.35 }}>{children}</h2>
      {description && <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted, marginTop: 4, lineHeight: 1.55, maxWidth: 760 }}>{description}</div>}
    </div>
  )
}

/** A card with a title row (title, description, actions on the right) and a body. */
export function Panel({
  title,
  description,
  actions,
  children,
  padded = true,
  style,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  padded?: boolean
  style?: CSSProperties
}) {
  return (
    <Card style={{ minWidth: 0, ...style }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, padding: '14px 18px 0' }}>
        <PanelTitle description={description}>{title}</PanelTitle>
        {actions}
      </div>
      <div style={{ padding: padded ? '14px 18px 18px' : '12px 0 0' }}>{children}</div>
    </Card>
  )
}

/** Two- or three-way toggle: a recessed track with the active option raised out of it. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
  size = 'md',
}: {
  options: { value: T; label: string; title?: string }[]
  value: T
  onChange: (v: T) => void
  disabled?: boolean
  size?: 'sm' | 'md'
}) {
  const h = size === 'sm' ? 26 : 30
  return (
    <div
      role="group"
      style={{
        display: 'inline-flex',
        background: C.raised,
        border: `1px solid ${C.rule}`,
        borderRadius: 9,
        padding: 2,
        gap: 2,
        flex: 'none',
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
              height: h,
              background: active ? C.surface : 'transparent',
              color: active ? C.text : C.muted,
              border: `1px solid ${active ? C.rule : 'transparent'}`,
              boxShadow: active ? 'var(--shadow-card)' : 'none',
              borderRadius: 7,
              padding: '0 11px',
              cursor: disabled ? 'default' : 'pointer',
              fontFamily: F.body,
              fontWeight: active ? 600 : 500,
              fontSize: size === 'sm' ? 12 : 12.5,
              whiteSpace: 'nowrap',
              transition: 'background-color 120ms, color 120ms',
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

/** A headline number with its label above and a short note below. */
export function Stat({ label, value, color = C.text, note, delay = 0 }: { label: string; value: ReactNode; color?: string; note?: ReactNode; delay?: number }) {
  return (
    <div className="anim-fade-in" style={{ animationDelay: `${delay}ms`, minWidth: 0 }}>
      <SectionLabel>{label}</SectionLabel>
      <div style={{ fontFamily: F.display, fontWeight: 600, fontSize: 26, lineHeight: 1.15, letterSpacing: '-0.01em', color, marginTop: 6, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      {note && <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 4, lineHeight: 1.45 }}>{note}</div>}
    </div>
  )
}

/** A small rounded label: an index, a sector, a state. */
export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: 'neutral' | 'accent' | 'warn' | 'verified'; title?: string }) {
  const tones = {
    neutral: { color: C.dim, background: C.raised, border: C.rule },
    accent: { color: C.accent, background: C.accentSoft, border: C.edge },
    warn: { color: C.warn, background: C.warnSoft, border: 'transparent' },
    verified: { color: C.verified, background: C.verifiedSoft, border: 'transparent' },
  }[tone]
  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        height: 22,
        padding: '0 8px',
        borderRadius: 6,
        fontFamily: F.body,
        fontSize: 12,
        fontWeight: 500,
        whiteSpace: 'nowrap',
        color: tones.color,
        background: tones.background,
        border: `1px solid ${tones.border}`,
      }}
    >
      {children}
    </span>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div style={{ padding: '44px 24px', textAlign: 'center', color: C.muted, fontFamily: F.body, fontSize: 13.5, lineHeight: 1.7 }}>{children}</div>
}

/** Names what the person can actually check, not just "an error occurred". */
export function ErrorState({ title = 'The engine didn’t answer', message, hint }: { title?: string; message: string; hint?: ReactNode }) {
  return (
    <Card accent={C.red} style={{ padding: '14px 18px' }} className="anim-fade-up">
      <div style={{ fontFamily: F.body, fontWeight: 600, fontSize: 14, color: C.text }}>{title}</div>
      <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted, marginTop: 4, lineHeight: 1.6 }}>
        {message}
        {hint ? <> — {hint}</> : null}
      </div>
    </Card>
  )
}

/** A shimmering placeholder block. */
export function Skeleton({ w = '100%', h = 10, r = 4, style }: { w?: number | string; h?: number; r?: number; style?: CSSProperties }) {
  return <div style={{ width: w, height: h, background: C.rule, borderRadius: r, animation: 'shimmer 1.6s ease-in-out infinite', ...style }} />
}

/** Placeholder for a dashboard page while its data loads: a stat strip and two panels. */
export function DashboardSkeleton() {
  return (
    <div style={{ display: 'grid', gap: 16 }} aria-label="Loading">
      <Card style={{ padding: 18, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 20 }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>
            <Skeleton w={80} h={9} />
            <Skeleton w={110} h={24} style={{ marginTop: 10 }} />
          </div>
        ))}
      </Card>
      <Card style={{ padding: 18, display: 'grid', gap: 12 }}>
        <Skeleton w={180} h={12} />
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} h={12} style={{ opacity: 1 - i * 0.09 }} />
        ))}
      </Card>
    </div>
  )
}

/** Mirrors the real answer card: hero row (identity + three numbers), then prose lines fading downward. */
export function AnswerSkeleton() {
  return (
    <Card style={{ padding: 20 }}>
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <Skeleton w={70} h={8} />
          <Skeleton w={180} h={20} style={{ marginTop: 8 }} />
        </div>
        {[0, 1, 2].map((i) => (
          <div key={i}>
            <Skeleton w={60} h={8} />
            <Skeleton w={90} h={22} style={{ marginTop: 8 }} />
          </div>
        ))}
      </div>
      <div style={{ marginTop: 22, display: 'grid', gap: 10 }}>
        {[1, 0.94, 0.97, 0.7].map((w, i) => (
          <Skeleton key={i} w={`${w * 100}%`} h={10} style={{ opacity: 1 - i * 0.18 }} />
        ))}
      </div>
    </Card>
  )
}

/** Mirrors a filing page: title block, a table grid, then text lines fading toward the bottom. */
export function PageSkeleton() {
  return (
    <div style={{ background: C.surface, borderRadius: 8, padding: '28px 32px', height: '100%', border: `1px solid ${C.rule}` }}>
      <Skeleton w="38%" h={10} />
      <Skeleton w="26%" h={8} style={{ marginTop: 8 }} />
      <div style={{ marginTop: 24, display: 'grid', gap: 9 }}>
        {Array.from({ length: 14 }).map((_, i) => (
          <div key={i} style={{ display: 'flex', gap: 14, opacity: 1 - i * 0.045 }}>
            <Skeleton w="46%" h={7} />
            <div style={{ flex: 1 }} />
            {[40, 40, 40].map((w, j) => (
              <Skeleton key={j} w={w} h={7} />
            ))}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 26, display: 'grid', gap: 8 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} w={`${92 - (i % 3) * 7}%`} h={7} style={{ opacity: 0.7 - i * 0.09 }} />
        ))}
      </div>
    </div>
  )
}
