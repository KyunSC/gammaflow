// Display names for the symbols the dashboard tracks. Factual instrument
// names only — what the ticker is, not a claim about it.
export const DISPLAY = { 'ES=F': '/ES', 'NQ=F': '/NQ', '^VIX': 'VIX' }

export const NAMES = {
  'ES=F': 'E-mini S&P 500 futures',
  'NQ=F': 'E-mini Nasdaq-100 futures',
  SPY: 'SPDR S&P 500 ETF',
  QQQ: 'Invesco QQQ, Nasdaq-100 ETF',
  '^VIX': 'Cboe Volatility Index',
  'XEQT.TO': 'iShares Core Equity ETF Portfolio, TSX',
  'BTC-USD': 'Bitcoin',
  'ETH-USD': 'Ether',
  'SOL-USD': 'Solana',
}

// Symbols whose chart draws gamma-exposure levels (mirrors GEX_SOURCES on
// the ticker page): futures use the ETF's strikes converted to futures prices.
export const GEX = { 'NQ=F': 'QQQ', 'ES=F': 'SPY', QQQ: 'QQQ', SPY: 'SPY' }

export const displayName = (symbol) => DISPLAY[symbol] || symbol.replace(/-USD$/, '')
