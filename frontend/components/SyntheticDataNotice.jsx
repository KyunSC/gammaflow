import { DATA_SOURCE } from '../lib/dataSource.mjs'

/**
 * Corner label on every page of a synthetic build (lib/dataSource.mjs), so no
 * one mistakes the generated prices and GEX levels for a market feed.
 */
export default function SyntheticDataNotice() {
  if (DATA_SOURCE === 'real') return null
  return (
    <div
      role="note"
      aria-label="Prices, volume, GEX levels and backtest datasets on this site come from a seeded random generator. They are not real market data."
      style={{
        position: 'fixed',
        left: '50%',
        bottom: 6,
        transform: 'translateX(-50%)',
        zIndex: 50,
        padding: '3px 8px',
        borderRadius: 4,
        background: 'rgba(30, 30, 30, 0.85)',
        border: '1px solid #8a6d1d',
        color: '#f0c674',
        font: '11px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        // Never in the way of a click; the text says enough on its own.
        pointerEvents: 'none',
        whiteSpace: 'nowrap',
      }}
    >
      Simulated data · not real market prices
    </div>
  )
}
