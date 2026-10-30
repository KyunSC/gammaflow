// Synthetic incremental bars; see app/api/historical/route.js.
import { rowsSince, timestamp } from '../../../../lib/synthetic/market'
import { cleanSymbol, error, json, nowSeconds } from '../../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET(request) {
  const params = new URL(request.url).searchParams
  const symbol = cleanSymbol(params.get('symbol'))
  const since = Number(params.get('since'))
  if (!symbol || !Number.isFinite(since)) return error(400, 'symbol and since are required')
  const interval = params.get('interval') || '1d'
  const now = nowSeconds()
  // Generation is cheap, so lastFetched is only echoed for the client's bookkeeping.
  return json({ symbol, period: 'since', interval, timestamp: timestamp(now), synthetic: true, data: rowsSince(symbol, interval, since, now), unavailable: false, lastFetched: Math.floor(now / 60) * 60 })
}
