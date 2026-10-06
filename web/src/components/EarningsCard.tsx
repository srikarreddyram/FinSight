// How the stock moved around each earnings report (close before the report to the session after), against the
// market, with the typical size of the move and where the latest one ranks.
import { ColumnChart } from '../charts/ColumnChart'
import { ChartCard } from '../charts/core'
import { Skeleton } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getEarnings } from '../news/api'
import type { EarningsReaction } from '../news/types'
import { useData } from '../pages/data'
import { pct } from '../recs/format'

const short = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' })
const long = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

function Fact({ label, value, note, color }: { label: string; value: string; note?: string; color?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted }}>{label}</div>
      <div style={{ ...NUM, fontSize: 20, fontWeight: 650, color: color ?? C.text, marginTop: 2 }}>{value}</div>
      {note && <div style={{ fontFamily: F.body, fontSize: 12, color: C.muted, marginTop: 1 }}>{note}</div>}
    </div>
  )
}

function lastNote(s: EarningsReaction['summary']): string {
  if (!s.last) return ''
  const dir = s.last.vs_market < 0 ? 'drop' : 'gain'
  if (s.last_biggest_since === null && (s.count ?? 0) > 3) return `biggest ${dir} in ${s.count} reports`
  if (s.last_biggest_since) {
    const years = (Date.parse(s.last.date) - Date.parse(s.last_biggest_since)) / (365.25 * 864e5)
    if (years >= 1) return `biggest ${dir} since ${short(s.last_biggest_since)}`
  }
  return long(s.last.date)
}

export function EarningsCard({ ticker }: { ticker: string }) {
  const { data, error } = useData(() => getEarnings(ticker), ticker)
  if (error) return null // no earnings history (or no prices): the card simply isn't shown
  const ev = data?.events ?? []
  const s = data?.summary
  return (
    <ChartCard
      title="Earnings reactions"
      table={
        <table className="dash-table">
          <thead>
            <tr>
              <th className="left">Report</th>
              <th>Stock</th>
              <th>S&amp;P 500</th>
              <th>vs market</th>
            </tr>
          </thead>
          <tbody>
            {[...ev].reverse().map((r) => (
              <tr key={r.date}>
                <td className="left">{long(r.date)}</td>
                <td>{pct(r.change, 1, true)}</td>
                <td>{pct(r.market, 1, true)}</td>
                <td style={{ color: r.vs_market >= 0 ? CH.pos : CH.neg, fontWeight: 600 }}>{pct(r.vs_market, 1, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {!data ? (
        <Skeleton h={200} r={8} />
      ) : ev.length === 0 ? (
        <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>No earnings reports found in the past five years.</div>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 16, marginBottom: 14 }}>
            {s?.last && <Fact label="Latest report" value={pct(s.last.vs_market, 1, true)} note={lastNote(s)} color={s.last.vs_market >= 0 ? CH.pos : CH.neg} />}
            {s?.typical != null && <Fact label="Typical move" value={`±${(s.typical * 100).toFixed(1)}%`} note="median, vs market" />}
            {s?.up != null && <Fact label="Rose after" value={`${s.up} of ${s.count}`} note="reports" />}
            {s?.largest_down && <Fact label="Worst reaction" value={pct(s.largest_down.vs_market, 1, true)} note={long(s.largest_down.date)} color={CH.neg} />}
          </div>
          <ColumnChart
            name="Two-day move vs the S&P 500"
            categories={ev.map((r) => short(r.date))}
            values={ev.map((r) => r.vs_market)}
            color={(v) => (v >= 0 ? CH.pos : CH.neg)}
            format={(v) => pct(v, 1, true)}
            height={200}
            labels={ev.length <= 12}
          />
        </>
      )}
    </ChartCard>
  )
}
