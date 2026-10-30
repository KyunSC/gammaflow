// Synthetic /api/historical for the public build; GAMMAFLOW_DATA=real proxies to the backend instead (next.config.mjs).
import { historicalRows, timestamp } from '../../../lib/synthetic/market'
import { cleanSymbol, error, json, nowSeconds } from '../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET(request) {
  const params = new URL(request.url).searchParams
  const symbol = cleanSymbol(params.get('symbol'))
  if (!symbol) return error(400, 'symbol is required')
  const period = params.get('period') || '1mo'
  const interval = params.get('interval') || '1d'
  const now = nowSeconds()
  return json({ symbol, period, interval, timestamp: timestamp(now), synthetic: true, data: historicalRows(symbol, period, interval, now), unavailable: false, lastFetched: null })
}
