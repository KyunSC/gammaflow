import dynamic from 'next/dynamic'

// Variant 05, "Research Ledger": results read as a notebook entry, with every
// number's caveats (in-sample, run tally, costs, data holes) printed beside it.
const variant = {
  id: '05',
  name: 'Research Ledger',
  Home: dynamic(() => import('./Home')),
  Ticker: dynamic(() => import('./Ticker')),
  Backtest: dynamic(() => import('./Backtest'), {
    ssr: false,
    loading: () => (
      <div className="flex h-screen items-center justify-center font-mono text-xs text-dim">loading backtester…</div>
    ),
  }),
}
export default variant
