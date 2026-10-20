import dynamic from 'next/dynamic'

// Variant 02 — "Lab Ledger": the backtester as a research log entry, where
// every headline number is printed with the caveats that qualify it.
const variant = {
  id: '02',
  name: 'Lab Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}
export default variant
