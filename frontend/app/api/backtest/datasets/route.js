// Synthetic research catalog; GAMMAFLOW_DATA=real proxies to the backend's published artifacts instead.
import { json, researchCatalog } from '../../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export function GET() {
  return json(researchCatalog(), { cache: 'no-cache' })
}
