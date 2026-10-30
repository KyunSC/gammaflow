// Synthetic buy-and-hold benchmark closes; see lib/synthetic/api.js.
import { benchmark, error, json } from '../../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET(request) {
  const params = new URL(request.url).searchParams
  const body = benchmark(params.get('symbol') || 'SPY', params.get('start'), params.get('end'))
  if (body instanceof Error) return error(400, body.message)
  return json(body, { cache: 'public, max-age=3600' })
}
