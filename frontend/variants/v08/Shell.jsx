'use client'

import Link from 'next/link'
import { JetBrains_Mono, Inter } from 'next/font/google'
import './v08.css'

const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--font-jetbrains-mono', display: 'swap' })
const sans = Inter({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--font-inter', display: 'swap' })

/** Header shared by the dashboard and the chart page: the product name, the
 *  two places to go, and a status slot that says what the data is doing. */
export default function Shell({ current, status, children }) {
  return (
    <div className={`${mono.variable} ${sans.variable} v8 v8-site`}>
      <header className="v8-sitehead">
        <Link href="/" className="v8-wordmark">
          GammaFlow
        </Link>
        <nav className="v8-sitenav" aria-label="Primary">
          <Link href="/" aria-current={current === 'markets' ? 'page' : undefined}>
            Markets
          </Link>
          <Link href="/backtest">Backtest</Link>
        </nav>
        {status && (
          <div className="v8-sitestatus" role="status" aria-live="polite">
            {status}
          </div>
        )}
      </header>
      <main className="v8-sitemain">{children}</main>
    </div>
  )
}
