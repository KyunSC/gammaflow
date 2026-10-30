// Synthetic /api/market for the public build; GAMMAFLOW_DATA=real proxies to the backend instead (next.config.mjs).
import { quote, timestamp } from '../../../lib/synthetic/market'
import { cleanSymbol, json, nowSeconds } from '../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET(request) {
  const params = new URL(request.url).searchParams
  let tickers = params.getAll('tickers').flatMap((s) => s.split(',')).map(cleanSymbol).filter(Boolean)
  if (!tickers.length) tickers = ['SPY', 'ES=F']
  const now = nowSeconds()
  return json({ timestamp: timestamp(now), synthetic: true, tickers: tickers.slice(0, 25).map((s) => quote(s, now)) })
}
