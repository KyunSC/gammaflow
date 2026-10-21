import dynamic from 'next/dynamic'

// UI 06 — "Session Ledger". One ruled surface instead of a grid of cards;
// the caveats (sample data, in-sample, run count, costs, data gaps) sit next
// to the headline numbers rather than behind the Advanced switch.
const variant = {
  id: '06',
  name: 'Session Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}
export default variant
