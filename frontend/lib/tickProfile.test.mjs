import test from 'node:test'
import assert from 'node:assert/strict'
import { createJiti } from 'jiti'
const jiti = createJiti(import.meta.url)
const { fetchCoverage, __resetTickProfileCaches } = await jiti.import('./tickProfile.js')

const SESSIONS = [[1_000_000, 1_023_400]]

// Stubs fetch with one response per call; returns the list of requested URLs.
function stubFetch(t, responses) {
  const calls = []
  const realFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    calls.push(url)
    const { status = 200, body = {} } = responses[Math.min(calls.length - 1, responses.length - 1)]
    return { ok: status >= 200 && status < 300, status, json: async () => body }
  }
  t.after(() => { globalThis.fetch = realFetch })
  __resetTickProfileCaches()
  return calls
}

const ok = { status: 200, body: { tickSize: 0.25, sessions: SESSIONS } }

test('a failed coverage lookup is evicted and retried on the next call', async (t) => {
  const calls = stubFetch(t, [{ status: 503 }, ok])
  await assert.rejects(fetchCoverage('NQ=F'))
  assert.deepEqual(await fetchCoverage('NQ=F'), SESSIONS)
  assert.equal(calls.length, 2)
})

test('a successful coverage lookup is cached', async (t) => {
  const calls = stubFetch(t, [ok])
  assert.deepEqual(await fetchCoverage('NQ=F'), SESSIONS)
  assert.deepEqual(await fetchCoverage('NQ=F'), SESSIONS)
  assert.equal(calls.length, 1)
})

test('an incompatible tick size caches as no coverage', async (t) => {
  const calls = stubFetch(t, [{ status: 200, body: { tickSize: 1, sessions: SESSIONS } }])
  assert.deepEqual(await fetchCoverage('NQ=F'), [])
  assert.deepEqual(await fetchCoverage('NQ=F'), [])
  assert.equal(calls.length, 1)
})

test('coverage is refetched after the TTL', async (t) => {
  const calls = stubFetch(t, [ok])
  const realNow = Date.now
  let now = realNow()
  Date.now = () => now
  t.after(() => { Date.now = realNow })
  await fetchCoverage('NQ=F')
  now += 9 * 60 * 1000
  await fetchCoverage('NQ=F')
  assert.equal(calls.length, 1)
  now += 2 * 60 * 1000
  await fetchCoverage('NQ=F')
  assert.equal(calls.length, 2)
})
