// Number formatting for the dashboard. Missing values read as an en dash, never as 0.
const DASH = '–'

export function pct(v: number | null | undefined, digits = 1, signed = false): string {
  if (v == null || Number.isNaN(v)) return DASH
  const s = (v * 100).toFixed(digits)
  return `${signed && v > 0 ? '+' : ''}${s}%`
}

export function num(v: number | null | undefined, digits = 2, signed = false): string {
  if (v == null || Number.isNaN(v)) return DASH
  return `${signed && v > 0 ? '+' : ''}${v.toFixed(digits)}`
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
