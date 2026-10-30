// Synthetic GEX levels for the public build; GAMMAFLOW_DATA=real proxies to the backend instead (next.config.mjs).
import { gammaExposure } from '../../../lib/synthetic/gex'
import { cleanSymbol, error, json, nowSeconds } from '../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET(request) {
  const raw = new URL(request.url).searchParams.get('symbol')
  const symbol = raw === null ? 'QQQ' : cleanSymbol(raw)
  if (!symbol) return error(400, 'invalid symbol')
  return json({ ...gammaExposure(symbol, nowSeconds()), synthetic: true })
}
