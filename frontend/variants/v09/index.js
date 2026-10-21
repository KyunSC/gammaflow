import dynamic from 'next/dynamic'

// Design 09 — "Lab Ledger". Every result is stated as a sentence with its
// caveats attached; data gaps are drawn, counted and listed, never closed up.
const variant = {
  id: '09',
  name: 'Lab Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}
export default variant
