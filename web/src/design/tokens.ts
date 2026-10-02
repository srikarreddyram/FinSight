// Design tokens: the Shot Vision design-system structure with FinSight's own colour scheme.
// Components import these instead of typing literals, so no page drifts from the system by typo.
// Every colour is a CSS variable defined in index.css (light and dark), so theming stays in one place.
import type { CSSProperties } from 'react'

export const C = {
  bg: 'var(--color-paper)', // page background
  surface: 'var(--color-card)', // card background, one step up from bg
  raised: 'var(--color-raised)', // a card floating above another card
  rule: 'var(--color-line)', // hairline dividers
  edge: 'var(--color-edge)', // accent-tinted borders
  hover: 'var(--color-hover)', // accent-tinted hover fill
  text: 'var(--color-ink)', // primary text
  dim: 'var(--color-dim)', // secondary text
  muted: 'var(--color-muted)', // captions, disabled states
  accent: 'var(--color-accent)', // FinSight teal
  accentSoft: 'var(--color-accent-soft)',
  onAccent: 'var(--color-on-accent)', // legible text on an accent fill
  // Meaning colours: what a number or state is, never decoration.
  verified: 'var(--color-verified)', // printed on the cited page
  verifiedSoft: 'var(--color-verified-soft)',
  computed: 'var(--color-computed)', // computed in Python
  computedSoft: 'var(--color-computed-soft)',
  warn: 'var(--color-warn)', // refusals, removed sentences
  warnSoft: 'var(--color-warn-soft)',
  red: 'var(--color-red)', // errors
} as const

export const F = {
  display: "'Barlow Condensed', 'Arial Narrow', sans-serif", // headlines, big numbers: condensed, used sparingly
  mono: "'JetBrains Mono', ui-monospace, monospace", // ALL data, labels, captions, eyebrows
  body: "'Inter', ui-sans-serif, system-ui, sans-serif", // anything read at length
} as const

// Mono numerals still need tabular-nums to line up in columns.
export const NUM: CSSProperties = { fontFamily: F.mono, fontVariantNumeric: 'tabular-nums' }

// Quality ramp for relevance scores. The accent sits at "partial match" on purpose, so an average result
// reads as neutral information rather than spending the brand colour on it.
export const TIERS = [
  { min: 0.9, color: 'var(--color-verified)', label: 'Strong match' },
  { min: 0.7, color: 'var(--color-tier-good)', label: 'Good match' },
  { min: 0.4, color: 'var(--color-accent)', label: 'Partial match' },
  { min: 0.2, color: 'var(--color-warn)', label: 'Weak match' },
  { min: 0, color: 'var(--color-red)', label: 'Poor match' },
] as const

export function tierColor(pct: number | null | undefined): string {
  if (pct == null) return C.muted
  return (TIERS.find((t) => pct >= t.min) ?? TIERS[TIERS.length - 1]).color
}
