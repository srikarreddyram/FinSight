// The time machine: the watchlist as it stood in a past month — each company's return rank and risk grade from
// models trained only on earlier data — next to what happened over the following twelve months.
import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Avatar, Badge, Card, Segmented } from '../design/primitives'
import { C, CH, F, GRADE_LABELS, NUM, gradeColor } from '../design/tokens'
import { pct } from '../recs/format'
import { getAsOf, getAsOfMonths } from '../research/api'
import type { AsOfRow } from '../research/types'
import { go } from '../shell/routes'
import { useData } from './data'
import { GradeChip, Page } from './shared'

const PICKS = [
  { month: '2019-12', label: 'Before COVID' },
  { month: '2021-12', label: 'Before the 2022 sell-off' },
  { month: '2023-06', label: 'Mid-2023' },
]
const PAGE = 50
type Sort = 'rank' | 'grade' | 'next'
const label = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })

export function TimeMachine({ month }: { month: string }) {
  const { data: months } = useData(getAsOfMonths, 'months')
  const { data, error } = useData(() => getAsOf(month), month)
  const [index, setIndex] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>('rank')
  const [page, setPage] = useState(0)
  const indexes = useMemo(() => [...new Set((data?.rows ?? []).map((r) => r.tier).filter((t): t is string => !!t))].sort(), [data])
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const key = (r: AsOfRow) => (sort === 'rank' ? -(r.rank ?? -1) : sort === 'grade' ? (r.grade ?? 9) : -(r.next_12m ?? -9))
    return (data?.rows ?? []).filter((r) => (!index || r.tier === index) && (!q || r.ticker.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))).sort((a, b) => key(a) - key(b))
  }, [data, index, query, sort])
  const shown = rows.slice(page * PAGE, (page + 1) * PAGE)

  return (
    <Page title="Time machine" meta={<span style={{ fontFamily: F.body, fontSize: 13, color: C.muted }}>The watchlist as it stood, and what happened next</span>} error={error} loading={!data && !error}>
      <Card style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <input type="month" className="control" value={month} min={months?.[0]} max={months?.at(-1)} onChange={(e) => e.target.value && go(`/history/${e.target.value}`)} aria-label="Month" />
        <span aria-hidden style={{ width: 1, height: 20, background: C.rule }} />
        <Segmented size="sm" value={PICKS.some((p) => p.month === month) ? month : ''} onChange={(m) => m && go(`/history/${m}`)} options={PICKS.map((p) => ({ value: p.month, label: p.label }))} />
      </Card>

      {data && (
        <>
          <section style={{ display: 'grid', gap: 10 }}>
            <h2 style={{ fontFamily: F.display, fontSize: 17, fontWeight: 650, color: C.text, margin: '6px 2px 0' }}>Graded in {label(month)}, then over the next 12 months</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
              {data.by_grade.map((g) => (
                <Card key={g.grade} style={{ padding: 0, overflow: 'hidden' }}>
                  <div style={{ height: 4, background: gradeColor(g.grade) }} />
                  <div style={{ padding: '12px 14px', display: 'grid', gap: 8 }}>
                    <span style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.body, fontSize: 13.5, fontWeight: 650, color: C.text }}>
                      {g.grade} {GRADE_LABELS[g.grade - 1]}
                      <span style={{ ...NUM, fontWeight: 400, fontSize: 12, color: C.muted }}>{g.n}</span>
                    </span>
                    <div>
                      <div style={{ ...NUM, fontSize: 22, fontWeight: 650, color: C.text }}>{pct(g.severe, 0)}</div>
                      <div style={{ fontFamily: F.body, fontSize: 11.5, color: C.muted }}>fell 40% or more at some point</div>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.body, fontSize: 12, color: C.muted, borderTop: `1px solid ${C.rule}`, paddingTop: 8 }}>
                      <span>Median vs S&amp;P 500</span>
                      <span style={{ ...NUM, fontWeight: 600, color: (g.next_12m ?? 0) >= 0 ? CH.pos : CH.neg }}>{pct(g.next_12m, 1, true)}</span>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </section>

          <Card style={{ overflow: 'hidden' }}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', padding: '12px 14px', borderBottom: `1px solid ${C.rule}` }}>
              <span style={{ position: 'relative', flex: '1 1 220px' }}>
                <Search size={15} color={C.muted} style={{ position: 'absolute', left: 10, top: 10 }} />
                <input className="control" value={query} onChange={(e) => (setQuery(e.target.value), setPage(0))} placeholder="Search companies" style={{ width: '100%', paddingLeft: 32 }} />
              </span>
              <Segmented size="sm" value={index} onChange={(v) => (setIndex(v), setPage(0))} options={[{ value: '', label: 'All' }, ...indexes.map((i) => ({ value: i, label: i.replace('sp', 'S&P ') }))]} />
              <Segmented
                size="sm"
                value={sort}
                onChange={setSort}
                options={[
                  { value: 'rank', label: 'Rank then' },
                  { value: 'grade', label: 'Grade then' },
                  { value: 'next', label: 'What happened' },
                ]}
              />
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="dash-table">
                <thead>
                  <tr>
                    <th className="left">Company</th>
                    <th>Rank then</th>
                    <th className="left">Grade then</th>
                    <th>Next 12 months vs S&amp;P 500</th>
                    <th className="left">Fell 40%+</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.ticker} className={r.listed ? 'clickable' : undefined} onClick={r.listed ? () => go(`/company/${encodeURIComponent(r.ticker)}`) : undefined}>
                      <td className="left">
                        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <Avatar ticker={r.ticker.split('~')[0]} name={r.name} size={30} />
                          <span style={{ minWidth: 0 }}>
                            <span style={{ display: 'block', fontFamily: F.body, fontWeight: 600, color: C.text }}>{r.name}</span>
                            <span style={{ display: 'flex', gap: 6, alignItems: 'center', fontFamily: F.body, fontSize: 12, color: C.muted }}>
                              {r.ticker.split('~')[0]} {!r.listed && <Badge>since delisted</Badge>}
                            </span>
                          </span>
                        </span>
                      </td>
                      <td>{r.rank == null ? '–' : r.rank.toFixed(0)}</td>
                      <td className="left">
                        <GradeChip grade={r.grade} />
                      </td>
                      <td style={{ fontWeight: 600, color: r.next_12m == null ? C.muted : r.next_12m >= 0 ? CH.pos : CH.neg }}>{pct(r.next_12m, 1, true)}</td>
                      <td className="left">{r.severe ? <Badge tone="warn">fell 40%+</Badge> : r.severe === false ? <span style={{ color: C.muted }}>no</span> : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', fontFamily: F.body, fontSize: 12.5, color: C.muted }}>
              <span>
                {rows.length.toLocaleString()} companies · page {page + 1} of {Math.max(1, Math.ceil(rows.length / PAGE))}
              </span>
              <span style={{ display: 'flex', gap: 6 }}>
                <button type="button" className="btn btn-secondary btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <button type="button" className="btn btn-secondary btn-sm" disabled={(page + 1) * PAGE >= rows.length} onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
              </span>
            </div>
          </Card>
        </>
      )}
    </Page>
  )
}
