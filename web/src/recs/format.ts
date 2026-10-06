// Number formatting for the dashboard. Missing values read as an en dash, never as 0.
const DASH = '–'

const MINUS = '\u2212' // a true minus sign: a hyphen sits too short and loose in tabular figures

/** A fixed-decimal number with a typographic minus; a value that rounds to zero carries no sign. */
function signedFixed(v: number, digits: number, plus: boolean): string {
  const s = Math.abs(v).toFixed(digits)
  if (Number(s) === 0) return s
  return `${v < 0 ? MINUS : plus ? '+' : ''}${s}`
}

export function pct(v: number | null | undefined, digits = 1, signed = false): string {
  if (v == null || Number.isNaN(v)) return DASH
  return `${signedFixed(v * 100, digits, signed)}%`
}

export function num(v: number | null | undefined, digits = 2, signed = false): string {
  if (v == null || Number.isNaN(v)) return DASH
  return signedFixed(v, digits, signed)
}

export function cap(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  return `$${(v / 1e6).toFixed(0)}M`
}

export function monthLabel(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`)
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}
