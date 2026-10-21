import dynamic from 'next/dynamic'

// Variant 07 — "Run Ledger". Results are written up as a ruled ledger: the
// verdict in words first, the data holes next to the trades they touch, and
// the robustness checks as a row whose labels say what has and hasn't been run.
const variant = {
  id: '07',
  name: 'Run Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}

export default variant
