/**
 * Synthetic dealer gamma for the public site, in the shape of GET /api/gamma.
 *
 * A made-up open-interest ladder (calls stacked above spot, puts below, extra
 * size on round strikes and one or two seeded "walls") is fixed per symbol and
 * day, then priced with Black-Scholes gamma at the synthetic spot every five
 * minutes, like the real scheduler. Key levels use the backend's own rules
 * (GammaExposureComputeService.identifyKeyLevels). Nothing comes from a real
 * option chain.
 */
import { FUTURES_FOR, dailySigma, gaussian, hash, lastSessionDay, marketOpen, previousTradingDay, quote, rng, symbolSpec, dayBar, dayString, timestamp } from './market'

const SNAPSHOT_SECONDS = 300
const round2 = (x) => Math.round(x * 100) / 100

function bsGamma(s, k, t, sigma) {
  if (t <= 0 || sigma <= 0) return 0
  const d1 = (Math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * Math.sqrt(t))
  return Math.exp(-0.5 * d1 * d1) / Math.sqrt(2 * Math.PI) / (s * sigma * Math.sqrt(t))
}

/** Next expiries after `day`: same-day, Friday weekly, third-Friday monthly. */
function expiries(day) {
  const out = [day]
  let d = day + 1
  while (new Date(d * 86400000).getUTCDay() !== 5) d++
  out.push(d)
  for (let k = d + 7; out.length < 4; k += 7) {
    const date = new Date(k * 86400000)
    if (date.getUTCDate() >= 15 && date.getUTCDate() <= 21) out.push(k)
  }
  return [...new Set(out)]
}

/** Per-strike GEX ladder for `symbol` at `now` (strikes ascending). */
export function gexLadder(symbol, now = Date.now() / 1000) {
  const spec = symbolSpec(symbol)
  const day = lastSessionDay(spec, now)
  const anchor = dayBar(spec, previousTradingDay(spec, day), now)?.c
  const spot = quote(spec.symbol, now).price
  if (!anchor || !spot) return { spec, day, spot, strikes: [] }
  const step = anchor >= 200 ? 1 : anchor >= 50 ? 0.5 : 0.25
  const r = rng(hash(`gex:${spec.symbol}:${day}`))
  const callWall = anchor * (1 + 0.01 + 0.03 * r())
  const putWall = anchor * (1 - 0.01 - 0.04 * r())
  const iv = Math.max(0.08, dailySigma(spec.fam, day) * Math.sqrt(252) * 1.1)
  const exps = expiries(day)
  const tradingMinutesLeft = Math.max(30, (Math.ceil(now / 86400) * 86400 - now) / 60)
  const tenors = exps.map((e, i) => (i === 0 ? tradingMinutesLeft / (390 * 252) : (e - day + 0.5) / 365))
  const weights = [0.3, 0.25, 0.25, 0.2]
  const strikes = []
  const lo = Math.ceil((anchor * 0.92) / step) * step
  const hi = Math.floor((anchor * 1.08) / step) * step
  for (let k = lo; k <= hi + 1e-9; k = Math.round((k + step) * 1e6) / 1e6) {
    const m = Math.log(k / anchor)
    const round = Math.abs(k % (step * 10)) < 1e-9 ? 2.6 : Math.abs(k % (step * 5)) < 1e-9 ? 1.7 : 1
    const noise = Math.exp(0.45 * gaussian(r))
    let callOi = (Math.exp(-(((m - 0.01) / 0.025) ** 2)) + 0.25 * Math.exp(-Math.abs(m) / 0.05)) * round * noise
    let putOi = (0.95 * Math.exp(-(((m + 0.015) / 0.03) ** 2)) + 0.3 * Math.exp(-Math.abs(m) / 0.05)) * round * Math.exp(0.45 * gaussian(r))
    if (Math.abs(k - callWall) < step / 2 + 1e-9) callOi *= 3.5
    if (Math.abs(k - putWall) < step / 2 + 1e-9) putOi *= 3.5
    let gc = 0
    let gp = 0
    tenors.forEach((t, i) => {
      // Put skew: downside strikes trade richer vol.
      const sigma = iv * Math.max(0.5, 1 - 1.5 * m)
      const g = bsGamma(spot, k, t, sigma) * weights[i] * 100 * spot * spot * 0.01
      gc += g * callOi * 3000
      gp -= g * putOi * 3000
    })
    strikes.push({ strike: round2(k), gexCall: Math.round(gc), gexPut: Math.round(gp), gex: Math.round(gc + gp) })
  }
  return { spec, day, spot, strikes, expirations: exps.map(dayString) }
}

/** Same selection as GammaExposureComputeService.identifyKeyLevels. */
export function keyLevels(strikes, spot) {
  const levels = []
  if (!strikes.length) return levels
  let callWall = null
  let putWall = null
  for (const s of strikes) {
    if (s.gex > 0 && (!callWall || s.gex > callWall.gex)) callWall = s
    if (s.gex < 0 && (!putWall || s.gex < putWall.gex)) putWall = s
  }
  if (callWall) levels.push({ ...callWall, label: 'call_wall' })
  if (putWall) levels.push({ ...putWall, label: 'put_wall' })
  let cumulative = 0
  let prevCum = null
  let prev = null
  let flip = null
  let best = Infinity
  for (const s of strikes) {
    cumulative += s.gex
    if (prevCum !== null && prevCum * cumulative < 0 && prev) {
      const weight = Math.abs(prevCum) / (Math.abs(prevCum) + Math.abs(cumulative))
      const at = prev.strike + weight * (s.strike - prev.strike)
      if (Math.abs(at - spot) < best) {
        best = Math.abs(at - spot)
        flip = { strike: round2(at), gex: 0, gexCall: 0, gexPut: 0, label: 'zero_gamma' }
      }
    }
    prevCum = cumulative
    prev = s
  }
  if (flip) levels.push(flip)
  const pos = strikes.filter((s) => s.gex > 0 && s !== callWall).sort((a, b) => b.gex - a.gex).slice(0, 3)
  const neg = strikes.filter((s) => s.gex < 0 && s !== putWall).sort((a, b) => a.gex - b.gex).slice(0, 3)
  for (const s of pos) levels.push({ ...s, label: 'significant_pos' })
  for (const s of neg) levels.push({ ...s, label: 'significant_neg' })
  return levels
}

/** Body of GET /api/gamma for the latest five-minute snapshot. */
export function gammaExposure(symbol, now = Date.now() / 1000) {
  const at = Math.floor(now / SNAPSHOT_SECONDS) * SNAPSHOT_SECONDS
  const ladder = gexLadder(symbol, at)
  const spec = ladder.spec
  const futures = FUTURES_FOR[spec.symbol]
  const futuresPrice = futures ? quote(futures, at).price : ladder.spot
  const ratio = ladder.spot ? futuresPrice / ladder.spot : 1
  return {
    timestamp: timestamp(at),
    marketOpen: marketOpen(at),
    etfPrice: ladder.spot,
    futuresPrice,
    conversionRatio: Math.round(ratio * 1e6) / 1e6,
    expirationsUsed: ladder.expirations || [],
    levels: keyLevels(ladder.strikes, ladder.spot).map((l) => ({
      strikeEtf: l.strike,
      strikeFutures: round2(l.strike * ratio),
      gex: l.gex,
      gexCall: l.gexCall,
      gexPut: l.gexPut,
      label: l.label,
    })),
  }
}
