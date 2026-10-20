import dynamic from 'next/dynamic'

// Variant 01 — "Evidence Ledger": every result is printed next to the checks
// that could rule it out (see SUMMARY in studies/ui-alternatives/01).
const variant = {
  id: '01',
  name: 'Evidence Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), { ssr: false }),
}
export default variant
