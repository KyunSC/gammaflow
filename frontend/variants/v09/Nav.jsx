'use client'

import Link from 'next/link'
import s from './Nav.module.css'

/** One top bar for all three pages, so moving between them never changes the
 *  furniture. `extra` sits after the links, `right` at the far end. */
export default function Nav({ current, extra, right, tickerLabel, tickerHref }) {
  return (
    <nav className={s.bar} aria-label="Main">
      <Link href="/" className={s.brand}>GammaFlow</Link>
      <span className={s.links}>
        <Link href="/" className={s.link} aria-current={current === 'markets' ? 'page' : undefined}>Markets</Link>
        {tickerLabel && (
          <Link href={tickerHref} className={s.link} aria-current={current === 'ticker' ? 'page' : undefined}>{tickerLabel}</Link>
        )}
        <Link href="/backtest" className={s.link} aria-current={current === 'backtest' ? 'page' : undefined}>Backtester</Link>
      </span>
      {extra && <span className={s.extra}>{extra}</span>}
      {right && <span className={s.right}>{right}</span>}
    </nav>
  )
}
