'use client'

import './v10.css'
import Link from 'next/link'
import { JetBrains_Mono, Inter } from 'next/font/google'

const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--l10-mono', display: 'swap' })
const sans = Inter({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--l10-sans', display: 'swap' })

/** Page frame for the dashboard and ticker pages: the same top line as the backtester. */
export default function Shell({ current, meta, children }) {
  return (
    <div className={`${mono.variable} ${sans.variable} l10-page`}>
      <nav className="l10-nav" aria-label="Main">
        <Link href="/" className="l10-wordmark">GammaFlow</Link>
        <Link href="/" aria-current={current === 'markets' ? 'page' : undefined}>Markets</Link>
        <Link href="/backtest" aria-current={current === 'backtest' ? 'page' : undefined}>Backtester</Link>
        {meta && <span className="l10-nav-meta" aria-live="polite">{meta}</span>}
      </nav>
      {children}
    </div>
  )
}
