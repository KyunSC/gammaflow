import dynamic from 'next/dynamic'

// UI 03, "Research Ledger". See SUMMARY.md in the study folder.
const variant = {
  id: '03',
  name: 'Research Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}
export default variant
