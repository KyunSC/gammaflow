// Variant 08 — "Lab Ledger". Every result sits next to the things that could
// make it wrong: runs tally, sample label, buy & hold, costs and data holes.
import dynamic from 'next/dynamic'

const variant = {
  id: '08',
  name: 'Lab Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}

export default variant
