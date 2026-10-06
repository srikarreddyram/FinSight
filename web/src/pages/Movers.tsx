// The universe's biggest moves against their sector, over a day, a week or a month. A row opens the company's
// page on the same window, where the move is broken down and investigated.
import { LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError } from '../api'
import { Avatar, Badge, Card, PanelTitle, Segmented, Stat } from '../design/primitives'
import { C, CH, F, NUM } from '../design/tokens'
import { getScan } from '../news/api'
import type { MoverRow, MoveWindow, Scan } from '../news/types'
import { pct } from '../recs/format'
import { Page, StatRow } from './shared'

const WINDOWS: { value: MoveWindow; label: string }[] = [
  { value: '1d', label: '1 day' },
  { value: '1w', label: '1 week' },
  { value: '1m', label: '1 month' },
]

const tone = (v: number | null) => (v == null ? C.muted : v > 0 ? CH.pos : v < 0 ? CH.neg : C.muted)
const longDate = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

export function Movers() {
  const [window, setWindow] = useState<MoveWindow>('1w')
  const [scan, setScan] = useState<Scan | null>(null)
  const [error, setError] = useState<string | null>(null)

  // The first scan of the day takes a couple of minutes; poll until it is ready.
  useEffect(() => {
    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = () =>
      getScan(window)
        .then((s) => {
          if (!live) return
          setScan(s)
          setError(s.status === 'error' ? (s.error ?? 'The scan failed') : null)
          if (s.status === 'building') timer = setTimeout(load, 4000)
        })
        .catch((e) => live && setError(e instanceof ApiError ? e.message : String(e)))
    load()
    return () => {
      live = false
      if (timer) clearTimeout(timer)
    }
  }, [window])

  const ready = scan?.status === 'ready'
  return (
    <Page
      title="Movers"
      meta={ready && scan.as_of ? <Badge tone="accent">Prices to {longDate(scan.as_of)}</Badge> : undefined}
      aside={<Segmented value={window} onChange={setWindow} options={WINDOWS} />}
      error={error}
      loading={!scan}
    >
      {scan?.status === 'building' && (
        <Card style={{ padding: '28px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <LoaderCircle size={18} className="animate-spin" color={C.accent} />
          <div>
            <div style={{ fontFamily: F.body, fontSize: 14, fontWeight: 600, color: C.text }}>Fetching today’s prices for the whole universe</div>
            <div style={{ fontFamily: F.body, fontSize: 13, color: C.muted, marginTop: 2 }}>About two minutes, once a day; this page updates on its own.</div>
          </div>
        </Card>
      )}
      {ready && scan.breadth && (
        <>
          <StatRow>
            <Stat label="S&P 500" value={<span style={{ color: tone(scan.market ?? 0) }}>{pct(scan.market, 1, true)}</span>} note={WINDOWS.find((w) => w.value === window)?.label} />
            <Stat label="Advancing" value={scan.breadth.up.toLocaleString()} note="companies up" />
            <Stat label="Declining" value={scan.breadth.down.toLocaleString()} note="companies down" />
          </StatRow>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <MoverTable title="Top gainers" rows={scan.gains ?? []} window={window} />
            <MoverTable title="Top losers" rows={scan.falls ?? []} window={window} />
          </div>
        </>
      )}
    </Page>
  )
}

function MoverTable({ title, rows, window }: { title: string; rows: MoverRow[]; window: MoveWindow }) {
  return (
    <Card style={{ overflow: 'hidden', minWidth: 0 }}>
      <div style={{ padding: '16px 18px 8px' }}>
        <PanelTitle>{title}</PanelTitle>
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: '0 8px 8px' }}>
        {rows.map((r) => {
          const href = `/company/${encodeURIComponent(r.ticker)}?w=${window}`
          return (
            <li key={r.ticker}>
              <a href={`#${href}`} className="hover-lift" style={{ display: 'grid', gridTemplateColumns: '40px minmax(0, 1fr) auto', alignItems: 'center', gap: 12, padding: '10px', borderRadius: 10, border: '1px solid transparent', textDecoration: 'none', color: C.text }}>
                <Avatar ticker={r.ticker} name={r.name} size={40} />
                <span style={{ minWidth: 0 }}>
                  <span className="truncate" style={{ display: 'block', fontFamily: F.body, fontSize: 14.5, fontWeight: 600 }}>
                    {r.name ?? r.ticker}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2, fontFamily: F.body, fontSize: 12.5, color: C.muted, flexWrap: 'wrap' }}>
                    <span style={{ ...NUM, fontWeight: 600 }}>{r.ticker}</span>· {r.index}
                    {r.max_day != null && Math.abs(r.max_day) >= 0.4 && (
                      <Badge tone="warn" title="One trading day accounts for most of this move. Check the company page: a spin-off can look like a fall.">
                        1-day {pct(r.max_day, 0, true)}
                      </Badge>
                    )}
                  </span>
                </span>
                <span style={{ textAlign: 'right' }}>
                  <span style={{ ...NUM, display: 'block', fontSize: 14.5, fontWeight: 600 }}>{r.price != null ? `$${r.price.toFixed(2)}` : '–'}</span>
                  <span style={{ ...NUM, display: 'block', fontSize: 13, fontWeight: 600, color: tone(r.change), marginTop: 2 }}>{pct(r.change, 2, true)}</span>
                  <span style={{ ...NUM, display: 'block', fontSize: 12, color: C.muted, marginTop: 1 }}>{pct(r.vs_sector ?? r.vs_market, 1, true)} vs sector</span>
                </span>
              </a>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
