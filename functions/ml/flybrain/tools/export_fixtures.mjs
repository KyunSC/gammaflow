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
const { resolvePlan, FIRM_LIST, sizesFor, PROP_ASOF, APEX_PRICES } = jiti(path.join(frontend, 'lib/backtest/prop/firms.js'))
const { runProp } = jiti(path.join(frontend, 'lib/backtest/prop/stats.js'))
const { sharpeInference, deflatedSharpe, normCdf, normInv } = jiti(path.join(frontend, 'lib/backtest/stats.js'))
const { mulberry32 } = jiti(path.join(frontend, 'lib/backtest/metrics.js'))
const out = path.resolve(here, '../fixtures')
const write = (name, value) => fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2)+'\n')
const plans = []
for (const firm of FIRM_LIST) for (const plan of Object.keys(firm.plans)) for (const size of sizesFor(firm, firm.plans[plan])) for (const dll of [true,false]) plans.push(resolvePlan({firm:firm.id, plan, size:size.id, dll}))
write('lucid_plans.json', {asof:PROP_ASOF, plans, apex:APEX_PRICES})
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
const addCase=(plan)=>cases.push({plan,output:runProp({result,time,plan,...opts,keepAttempts:true})})
// Other firms run the same code at every size, so 50K covers their rules and keeps this tracked file small.
for (const plan of plans) if (plan.firm==='lucid'||plan.size==='50k') addCase(plan)
// Lucid's dailyIntraday plan covers one intraday-trailing evaluation; these edited plans cover the lock
// variants no listed plan has: trailing that never stops, stops at the target, stops at the default,
// and an EOD eval that never stops.
for (const overrides of [{evalDrawdown:'intraday',evalLockOffset:null},{evalDrawdown:'intraday',evalLockOffset:3000},{evalDrawdown:'intraday'},{evalLockOffset:null}]) {
  addCase(resolvePlan({firm:'lucid',plan:'flex',size:'50k',dll:false,overrides}))
}
// Funded scaling plans only bite when the replay knows the traded size: run them at the plan's full size.
for (const [firm,name] of [['topstep','standard'],['alpha','zero'],['alpha','standard']]) {
  const plan=resolvePlan({firm,plan:name,size:'50k'})
  plan.tradedMinis=plan.maxMinis
  addCase(plan)
}
write('prop_parity.json',{result,time,...opts,cases})
const stats=[]
for (const returns of [[],[0],[0,0,0],Array.from({length:1000},()=>rng()*.002-.00095),[-.2,0,0,.1,.02,.05]]) {
  const inference=sharpeInference(returns,78*252)
  const trials=[-.02,.01,.04,.005,.1]
  stats.push({returns,inference,trials,deflated:deflatedSharpe(inference,trials)})
}
write('stats_parity.json',{cases:stats,norm:[.001,.02,.3,.5,.7,.98,.999].map(p=>({p,inv:normInv(p),cdf:normCdf(normInv(p))})),rng:Array.from({length:20},mulberry32(42))})
console.log(`Exported ${plans.length} plans and ${cases.length} parity cases to ${out}`)
