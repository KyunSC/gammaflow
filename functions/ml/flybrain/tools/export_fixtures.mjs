// Run from frontend; all inputs are synthetic, no market data is accessed.
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'
const here = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(here, '../../../../frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const { createJiti } = require('jiti')
const jiti = createJiti(import.meta.url)
const { resolvePlan, sizesFor, FIRMS, SIZES, PROP_ASOF } = jiti(path.join(frontend, 'lib/backtest/prop/firms.js'))
const { runProp } = jiti(path.join(frontend, 'lib/backtest/prop/stats.js'))
const { perpMarket, ratesFor, leverageFor } = jiti(path.join(frontend, 'lib/backtest/prop/perps.js'))
const { sharpeInference, deflatedSharpe, normCdf, normInv } = jiti(path.join(frontend, 'lib/backtest/stats.js'))
const { mulberry32 } = jiti(path.join(frontend, 'lib/backtest/metrics.js'))
const out = path.resolve(here, '../fixtures')
const write = (name, value) => fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2)+'\n')
const plans = []
for (const plan of Object.keys(FIRMS.lucid.plans)) for (const size of SIZES) for (const dll of [true,false]) plans.push(resolvePlan({plan, size:size.id, dll}))
write('lucid_plans.json', {asof:PROP_ASOF, plans})
const rng = mulberry32(17)
const result = {equity:[], barLo:[], barHi:[], barOpen:[]}
const time=[]; let equity=50000
for (let day=0; day<60; day++) {
  const drift = (rng()-.40)*65
  for (let bar=0; bar<78; bar++) {
    const open=equity
    equity += drift+(rng()-.5)*180
    result.equity.push(equity)
    result.barOpen.push(open)
    result.barLo.push(Math.min(open,equity)-rng()*100)
    result.barHi.push(Math.max(open,equity)+rng()*100)
    time.push(Date.UTC(2024,0,2+day,14,30+5*bar)/1000)
  }
}
const opts={initialCapital:50000,paths:200,seed:42,horizon:250,blockSize:5}
const cases=[]
for (const plan of plans) cases.push({plan,output:runProp({result,time,plan,...opts,keepAttempts:true})})
write('prop_parity.json',{result,time,...opts,cases})
// MyFundedPerps: every plan / size / DLL option on a synthetic 24/7 hourly path
// that crosses the March DST switch, holds overnight, and goes quiet for nine
// days, so NY-midnight days, the flat-day payout gate and inactivity all bite.
const mfpPlans = []
for (const plan of Object.keys(FIRMS.mfp.plans)) for (const size of sizesFor('mfp', plan)) for (const dll of FIRMS.mfp.plans[plan].dllOptional ? [true,false] : [true]) mfpPlans.push(resolvePlan({firm:'mfp', plan, size:size.id, dll}))
write('mfp_plans.json', {asof:FIRMS.mfp.asof, plans:mfpPlans})
// MFP market costs under Elite, for Python research; slippage band ceilings of Infinity export as null.
const elite = resolvePlan({firm:'mfp', plan:'elite', size:'50k', dll:true})
const mfpMarkets = {}
for (const symbol of ['BTC-USD', 'ETH-USD', 'SOL-USD']) {
  const m = perpMarket(symbol)
  mfpMarkets[m.id] = {...m, ...ratesFor(m, elite), leverage: leverageFor(m, elite)}
}
write('mfp_markets.json', {asof:FIRMS.mfp.asof, plan:'elite', markets:mfpMarkets})
function mfpPath(balance, wild) {
  const scale = balance / 50000
  const r = {equity:[], barLo:[], barHi:[], barOpen:[], positions:[], trades:[]}
  const t = []
  let eq = balance, pos = 0, left = 0, entry = -1
  const rr = mulberry32(23)
  for (let i = 0; i < 24 * 45; i++) {
    const quiet = i >= 24 * 20 && i < 24 * 29
    if (left <= 0) {
      const want = quiet ? 0 : [0, 1, -1][Math.floor(rr() * 3)]
      if (want !== pos) {
        if (pos !== 0) r.trades.push({entryIdx: entry, exitIdx: i})
        if (want !== 0) entry = i
        pos = want
      }
      left = 3 + Math.floor(rr() * 28)
    }
    left--
    const open = eq
    eq += (pos * (rr() - 0.5) * (wild ? 520 : 200) + Math.abs(pos) * (wild ? 4 : 30)) * scale
    r.barOpen.push(open)
    r.equity.push(eq)
    r.barLo.push(Math.min(open, eq) - rr() * (wild ? 200 : 80) * scale * Math.abs(pos))
    r.barHi.push(Math.max(open, eq) + rr() * (wild ? 200 : 80) * scale * Math.abs(pos))
    r.positions.push(pos)
    t.push(Date.UTC(2026, 1, 20) / 1000 + i * 3600)
  }
  return {result: r, time: t}
}
// 'wild' hits the daily and static floors; 'calm' survives long enough to pay out and to go idle.
const mfpResults = {}
for (const size of FIRMS.mfp.sizes) {
  mfpResults[size.id] = mfpPath(size.balance, true)
  mfpResults[`${size.id}-calm`] = mfpPath(size.balance, false)
}
const mfpCases = mfpPlans.flatMap((plan) => [plan.size, `${plan.size}-calm`].map((key) => {
  const {result: r, time: t} = mfpResults[key]
  return {key, plan, output: runProp({result: r, time: t, plan, ...opts, initialCapital: plan.startBalance, keepAttempts: false})}
}))
write('mfp_parity.json', {results: mfpResults, ...opts, cases: mfpCases})
const stats=[]
for (const returns of [[],[0],[0,0,0],Array.from({length:1000},()=>rng()*.002-.00095),[-.2,0,0,.1,.02,.05]]) {
  const inference=sharpeInference(returns,78*252)
  const trials=[-.02,.01,.04,.005,.1]
  stats.push({returns,inference,trials,deflated:deflatedSharpe(inference,trials)})
}
write('stats_parity.json',{cases:stats,norm:[.001,.02,.3,.5,.7,.98,.999].map(p=>({p,inv:normInv(p),cdf:normCdf(normInv(p))})),rng:Array.from({length:20},mulberry32(42))})
console.log(`Exported ${plans.length} Lucid and ${mfpPlans.length} MyFundedPerps plan parity cases to ${out}`)
