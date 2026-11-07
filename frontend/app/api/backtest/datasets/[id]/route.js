// One synthetic research dataset. Ids carry their own window, so shared links replay.
import { error, json, researchArtifact } from '../../../../../lib/synthetic/api'

export const dynamic = 'force-dynamic'

export async function GET(_request, { params }) {
  const { id } = await params
  if (!/^[a-z0-9_-]+-[a-f0-9]{64}$/.test(id)) return error(400, 'Invalid dataset ID')
  const ds = researchArtifact(id)
  if (!ds) return error(404, 'Dataset version unavailable')
  return json(ds, { cache: 'public, max-age=31536000, immutable' })
}
