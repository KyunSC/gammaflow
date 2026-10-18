/**
 * MyFundedPerps markets and costs, as of 2026-10-18 (docs.myfundedperpetuals.com:
 * Commissions and Fees, Trading Guide, Elite Accounts; myfundedperpetuals.com/exposure-caps).
 *
 * A dataset symbol maps to the MFP market it stands in for. Crypto `*-USD`
 * bars are the market itself (MFP marks crypto off Hyperliquid / Binance, a
 * few bps apart). Index ETFs and CME futures are proxies for the NAS100 /
 * SP500 perps, which MFP marks off Hyperliquid and which also trade on
 * weekends, so the proxy misses basis and weekend moves.
 *
 * Costs are what MFP charges:
 *   commission  bps of each fill's notional, maker = taker
 *   swap        a daily rate charged hourly on notional, longs and shorts alike;
 *               venue funding does not touch the balance, so there is no carry
 *   slippage    the published worst-case bound per order notional, keyed on the
 *               market's open interest; unknown OI gets the worst band, as MFP does
 */

const CRYPTO = /^([A-Z0-9]+)-USD$/

/** Proxy datasets → MFP index market. */
const INDEX_PROXY = {
  QQQ: 'NAS100',
  'NQ=F': 'NAS100',
  'MNQ=F': 'NAS100',
  SPY: 'SP500',
  'ES=F': 'SP500',
  'MES=F': 'SP500',
}

/** Standard rates by asset class: commission bps per fill, swap bps per day. */
const RATES = {
  crypto: { commissionBps: 3, swapDailyBps: 3 },
  fx: { commissionBps: 0.25, swapDailyBps: 0.5 },
  index: { commissionBps: 0.5, swapDailyBps: 1.5 },
  stock: { commissionBps: 0.5, swapDailyBps: 1.5 },
  commodity: { commissionBps: 0.5, swapDailyBps: 1.5 },
}

/** Elite's reduced rates. Gold and WTI keep the standard swap. */
const ELITE_RATES = {
  NAS100: { commissionBps: 0.1, swapDailyBps: 1 },
  SP500: { commissionBps: 0.1, swapDailyBps: 1 },
}

/** Elite's boosted leverage, per account, on starting balance. */
const ELITE_LEVERAGE = { NAS100: 40, SP500: 40 }

/**
 * Highest leverage on the exposure-caps page, across products and sizes (the
 * page shows a range; per-product caps can be lower). Markets not listed there
 * — SOL among them — get 2×, the most common crypto value, until checked.
 */
const CRYPTO_LEVERAGE = { BTC: 10, ETH: 8, BNB: 5, DOGE: 3 }

/** Crypto with open interest well above $500M on the venues MFP uses. */
const DEEP_CRYPTO = new Set(['BTC', 'ETH', 'SOL'])

// [notional ceiling, bps] per band, ascending.
const SLIP_INDEX = [[100e3, 0.25], [200e3, 0.5], [1e6, 0.75], [Infinity, 1]]
const SLIP_OI_DEEP = [[100e3, 0.8], [500e3, 1.2], [Infinity, 2]]
const SLIP_OI_UNKNOWN = [[100e3, 6], [500e3, 10], [Infinity, 16]]

export function perpMarket(symbol) {
  if (typeof symbol !== 'string') return null
  const sym = symbol.toUpperCase()
  const crypto = sym.match(CRYPTO)
  if (crypto) {
    const base = crypto[1]
    return {
      id: base,
      symbol,
      assetClass: 'crypto',
      proxy: false,
      maxLeverage: CRYPTO_LEVERAGE[base] || 2,
      slippage: DEEP_CRYPTO.has(base) ? SLIP_OI_DEEP : SLIP_OI_UNKNOWN,
    }
  }
  const index = INDEX_PROXY[sym]
  if (index) {
    return { id: index, symbol, assetClass: 'index', proxy: true, maxLeverage: null, slippage: SLIP_INDEX }
  }
  return null
}

export function slippageFor(market, notional) {
  const band = market.slippage.find(([ceiling]) => notional <= ceiling)
  return band ? band[1] : market.slippage[market.slippage.length - 1][1]
}

/** Commission and swap for a market under a plan (Elite pays less on some). */
export function ratesFor(market, plan) {
  const std = RATES[market.assetClass] || RATES.stock
  return (plan?.boosted && ELITE_RATES[market.id]) || std
}

/** Leverage cap for a market under a plan; null when MFP does not publish one we checked. */
export function leverageFor(market, plan) {
  return (plan?.boosted && ELITE_LEVERAGE[market.id]) || market.maxLeverage
}

/**
 * Engine instrument and replay plan for a perps prop account. Sizing is either
 * a fixed risk per trade (a fraction of the starting balance, divided by the
 * stop distance) or a fixed notional (a multiple of the starting balance).
 * Either way it never reads the running balance, which the replay relies on.
 */
export function perpSetup({ prop, plan, symbol, costs, risk }) {
  const market = perpMarket(symbol)
  if (!market) return { error: `${symbol} has no MyFundedPerps market — use crypto (BTC-USD …) or an index proxy (QQQ, SPY, NQ=F, ES=F)` }
  const start = plan.startBalance
  const byRisk = prop.perpSizing === 'risk'
  if (byRisk && !(risk?.stopPct > 0)) return { error: 'Risk sizing needs a stop: set Stop (%) under exits, or size by notional' }
  const lev = leverageFor(market, plan)
  const maxNotional = lev ? lev * start : 0
  const riskUsd = byRisk ? Math.max(0, Number(prop.riskPct) || 0) / 100 * start : 0
  const wanted = byRisk ? riskUsd / (risk.stopPct / 100) : Math.max(0, Number(prop.leverage) || 0) * start
  const notional = maxNotional ? Math.min(wanted, maxNotional) : wanted
  const rates = ratesFor(market, plan)
  const num = (v, fallback) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? fallback : Number(v))
  const instrument = {
    kind: 'perp',
    market: market.id,
    riskUsd,
    notional: byRisk ? 0 : notional,
    maxNotional,
    commissionBps: num(prop.commissionBps, rates.commissionBps),
    slippageBps: num(prop.slippageBps, slippageFor(market, notional)),
    swapDailyBps: num(prop.swapDailyBps, rates.swapDailyBps),
    priceScale: 1,
  }
  return {
    plan,
    market,
    perp: true,
    proxy: market.proxy,
    notional,
    capped: maxNotional > 0 && wanted > maxNotional,
    leverage: notional / start,
    costs: { ...costs, initialCapital: start, instrument },
    // No forced flat: MFP allows overnight and weekend holds on 24/7 markets.
    risk: { ...risk, flatByEt: 0 },
  }
}
