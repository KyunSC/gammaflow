import Link from 'next/link'

/** Shared top line for the dashboard and chart pages. */
export default function Masthead({ current, children }) {
  return (
    <header className="v4-mast">
      <Link href="/" className="v4-brand">Gamma<span>Flow</span></Link>
      <nav className="v4-nav" aria-label="Primary">
        <Link href="/" aria-current={current === 'markets' ? 'page' : undefined}>Markets</Link>
        <Link href="/backtest">Backtester</Link>
      </nav>
      {children && <span className="v4-mast-meta">{children}</span>}
    </header>
  )
}
