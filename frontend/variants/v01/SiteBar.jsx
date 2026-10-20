'use client'

import Link from 'next/link'
import s from './site.module.css'

/** One top bar for all three pages: wordmark, where you are, and a slot on the
 *  right for page facts (last update, dataset, run count). */
export default function SiteBar({ current, crumb, right, className = '' }) {
  return (
    <header className={`${s.bar} ${className}`}>
      <Link href="/" className={s.brand}>Market data</Link>
      <nav className={s.nav} aria-label="Pages">
        <Link href="/" className={`${s.navLink} ${current === 'home' ? s.navActive : ''}`} aria-current={current === 'home' ? 'page' : undefined}>
          Dashboard
        </Link>
        {crumb && (
          <>
            <span className={s.crumbSep} aria-hidden="true">/</span>
            <span className={`${s.navLink} ${s.navActive}`} aria-current="page">{crumb}</span>
          </>
        )}
        <Link href="/backtest" className={`${s.navLink} ${current === 'backtest' ? s.navActive : ''}`} aria-current={current === 'backtest' ? 'page' : undefined}>
          Backtester
        </Link>
      </nav>
      {right && <div className={s.barRight}>{right}</div>}
    </header>
  )
}
