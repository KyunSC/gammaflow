/**
 * Which data this build serves.
 *
 * 'synthetic' (the default): every /api/* route is answered inside Next from
 * lib/synthetic (app/api/**), and the Spring backend is never contacted.
 * 'real': /api/* is proxied to the backend (Yahoo, Supabase, licensed tick
 * prints), as before. Yahoo, Databento and ThetaData terms don't allow
 * redistributing that data, so it is local-only: set GAMMAFLOW_DATA=real
 * (dev.sh does). A hosted build that asks for real data fails instead of
 * quietly serving it.
 */

// Platform variables that mark a hosted build or server.
const HOSTED_MARKERS = ['VERCEL', 'RENDER', 'NETLIFY', 'CF_PAGES', 'AWS_EXECUTION_ENV', 'WEBSITE_SITE_NAME']

export function resolveDataSource(env = process.env) {
  if (env.GAMMAFLOW_DATA !== 'real') return 'synthetic'
  const host = HOSTED_MARKERS.find((k) => env[k])
  if (host) {
    throw new Error(`GAMMAFLOW_DATA=real is local-only, but this build runs on a host (${host} is set). Real market data can't be redistributed; unset GAMMAFLOW_DATA.`)
  }
  return 'real'
}

// next.config.mjs inlines GF_DATA_SOURCE into server and browser bundles; outside
// Next (tests, scripts) it is unset, which reads as synthetic.
export const DATA_SOURCE = process.env.GF_DATA_SOURCE === 'real' ? 'real' : 'synthetic'
