// Exact volume-at-price comes from licensed Databento prints and is local-only.
// The public build simulates prints in the browser (lib/syntheticTickProfile.js)
// and never calls this; answer anything that does with a plain 404.
import { error } from '../../../../lib/synthetic/api'

export function GET() {
  return error(404, 'Trade-print volume profiles are only served on local builds')
}
