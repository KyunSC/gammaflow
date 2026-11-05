/**
 * One-time cleanup of the localStorage caches written before their keys carried
 * a data source (`marketDataCache:real:...` used to be `marketDataCache:...`).
 *
 * Nothing reads the old keys any more and max-age is only applied on read, so
 * without this they stay forever, holding bar arrays and ~1 MB research datasets
 * in the ~5 MB quota the new keys need. Cache writers call this first; it costs
 * one getItem once the flag is set and touches nothing rendered, so it can't
 * cause a hydration mismatch.
 */

const LEGACY_CACHE_PREFIXES = ['historicalDataCache:', 'marketDataCache:', 'backtestCache:']
// What follows those prefixes in a current key (see DATA_SOURCE in dataSource.mjs).
const SOURCE_SEGMENTS = ['real:', 'synthetic:']

export const SWEEP_FLAG_KEY = 'cacheSweepVersion'
// Bump to run the sweep again in browsers that already ran it.
export const SWEEP_VERSION = '1'

export function isLegacyCacheKey(key) {
  const prefix = LEGACY_CACHE_PREFIXES.find((p) => key.startsWith(p))
  if (!prefix) return false
  const rest = key.slice(prefix.length)
  return !SOURCE_SEGMENTS.some((s) => rest.startsWith(s))
}

export function sweepLegacyCaches(storage) {
  try {
    // Resolved in here because merely touching localStorage throws if it's blocked.
    const store = storage ?? globalThis.localStorage
    if (!store || store.getItem(SWEEP_FLAG_KEY) === SWEEP_VERSION) return
    // Snapshot first: removing while walking by index would skip keys.
    const keys = []
    for (let i = 0; i < store.length; i++) keys.push(store.key(i))
    for (const key of keys) {
      if (isLegacyCacheKey(key)) store.removeItem(key)
    }
    // Last, so a sweep that fails partway runs again on the next write.
    store.setItem(SWEEP_FLAG_KEY, SWEEP_VERSION)
  } catch { /* Storage is optional. */ }
}
