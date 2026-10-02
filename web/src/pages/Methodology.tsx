import type { ReactNode } from 'react'
import { Card, SectionLabel } from '../design/primitives'
import { C, F } from '../design/tokens'
import { getMeta } from '../recs/api'
import { monthLabel } from '../recs/format'
import { useData } from './data'
import { Page } from './shared'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card style={{ padding: '18px 20px' }}>
      <SectionLabel style={{ letterSpacing: '0.24em' }}>{title}</SectionLabel>
      <div style={{ fontFamily: F.body, fontSize: 14, color: C.dim, lineHeight: 1.7, marginTop: 10, maxWidth: 860, display: 'grid', gap: 10 }}>{children}</div>
    </Card>
  )
}

export function Methodology() {
  const { data: meta } = useData(getMeta)
  return (
    <Page title="Methodology" lead="How the numbers on this site are made, what they can and cannot tell you, and the biases that remain.">
      <Section title="Only what was public at the time">
        <p style={{ margin: 0 }}>
          Every figure is used from the day after the filing that reported it reached the SEC, never from the period it describes. A 10-K for 2018 filed in June 2019 does not exist in the data until June 2019. When a company restates a figure, the earlier months keep the version that was public then.
        </p>
        <p style={{ margin: 0 }}>
          A model for a given year is trained only on earlier years, and training rows whose 12-month outcome overlaps that year are removed. Settings are chosen inside each training window, never on the years being tested.
        </p>
      </Section>
      <Section title="Universe">
        <p style={{ margin: 0 }}>
          S&amp;P 500 members since 2010, including companies later removed, rebuilt from the index’s published additions and removals and matched to SEC company identifiers.
          {meta && ` The current watchlist covers ${meta.companies} companies as of ${monthLabel(meta.as_of)}.`}
        </p>
      </Section>
      <Section title="Known biases and limits">
        <p style={{ margin: 0 }}>
          <strong>Survivorship.</strong> Free price data drops companies that were acquired or delisted. Those companies’ fundamentals are in the data, but their returns are not, so results lean towards companies that survived, most in the earliest years.
        </p>
        <p style={{ margin: 0 }}>
          <strong>No proven edge in returns.</strong> Over ten test years the return model’s ranking was not distinguishable from no skill: its top-minus-bottom portfolio earned a little after costs, well within what chance produces. A few single signals, such as changes in leverage, held up better. The range of outcomes at any rank is far wider than the difference between ranks.
        </p>
        <p style={{ margin: 0 }}>
          <strong>Risk grades.</strong> The grades sort risk in the right order, but they are built mostly from the stock’s own past-year volatility: blending in the filing-based models improves on it only by a hair.
        </p>
        <p style={{ margin: 0 }}>
          <strong>Sectors.</strong> Sectors come from SEC industry codes, which differ from index providers’ sectors for some companies. Generic balance-sheet ratios mean less for banks, real-estate trusts and energy companies.
        </p>
        <p style={{ margin: 0 }}>
          <strong>One year held back.</strong> {meta?.holdout_note ?? 'The most recent full year is held out for a single final evaluation.'}
        </p>
      </Section>
      <Section title="What this is not">
        <p style={{ margin: 0 }}>
          This is a research and education project built on public SEC filings and free price data. Nothing here is personal financial advice, a recommendation to buy or sell a security, or a credit rating. There is no position sizing and no assessment of anyone’s circumstances.
        </p>
      </Section>
    </Page>
  )
}
