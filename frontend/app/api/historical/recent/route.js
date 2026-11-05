// Synthetic recent 1m bars; see app/api/historical/route.js.
import { recentRows, timestamp } from '../../../../lib/synthetic/market'
import { cleanSymbol, error, json, nowSeconds } from '../../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET(request) {
  const symbol = cleanSymbol(new URL(request.url).searchParams.get('symbol'))
  if (!symbol) return error(400, 'symbol is required')
  const now = nowSeconds()
  return json({ symbol, period: '1d', interval: '1m', timestamp: timestamp(now), synthetic: true, data: recentRows(symbol, now), unavailable: false, lastFetched: null })
}
