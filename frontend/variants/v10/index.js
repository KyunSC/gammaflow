// Variant 10 — "Research Ledger". See variants/README.md for the contract.
import dynamic from 'next/dynamic'

const variant = {
  id: '10',
  name: 'Research Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}
export default variant
