import dynamic from 'next/dynamic'

// UI 04 · Lab Ledger. Each backtest reads like an entry in a lab notebook:
// the result, then the caveats that qualify it, then the evidence. The
// hierarchy comes from type and hairline rules rather than boxes.
const variant = {
  id: '04',
  name: 'Lab Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}
export default variant
