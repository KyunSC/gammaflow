// Synthetic live tick; see app/api/market/route.js.
import { quote, timestamp } from '../../../../lib/synthetic/market'
import { cleanSymbol, error, json, nowSeconds } from '../../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET(request) {
  const symbol = cleanSymbol(new URL(request.url).searchParams.get('symbol'))
  if (!symbol) return error(400, 'symbol is required')
  const now = nowSeconds()
  return json({ timestamp: timestamp(now), synthetic: true, tickers: [quote(symbol, now)] })
}
