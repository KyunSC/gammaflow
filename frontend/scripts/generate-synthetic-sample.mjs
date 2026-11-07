#!/usr/bin/env node
/**
 * Writes the bundled backtest example (public/backtest/{index,qqq_5m,spy_5m}.json)
 * from lib/synthetic. Everything under public/ ships with the deployed site, so
 * it must never hold real (Yahoo/ThetaData-derived) data; the real export goes
 * to functions/ml/data/backtest_export (gitignored) instead.
 *
 *   npm run sample:synthetic
 *
 * Output is deterministic: rerunning it rewrites identical files.
 */
import { writeFile } from 'node:fs/promises'
import { createJiti } from 'jiti'

const jiti = createJiti(import.meta.url)
const { dayNumber } = await jiti.import(new URL('../lib/synthetic/market.js', import.meta.url).href)
const { researchDataset } = await jiti.import(new URL('../lib/synthetic/research.js', import.meta.url).href)

// Fixed window, so the example (and tests that read it) never shift.
const FROM = dayNumber(2026, 4, 27)
const TO = dayNumber(2026, 7, 10)
const OUT = new URL('../public/backtest/', import.meta.url)

const datasets = []
for (const symbol of ['QQQ', 'SPY']) {
  const ds = researchDataset(symbol, FROM, TO)
  const file = `${symbol.toLowerCase()}_5m.json`
  const body = JSON.stringify(ds)
  await writeFile(new URL(file, OUT), body)
  datasets.push({
    symbol,
    file,
    bars: ds.bars,
    start: ds.start,
    end: ds.end,
    interval: ds.interval,
    horizonMinutes: ds.horizonMinutes,
    sizeKb: Math.round(body.length / 1024),
    hasMl: true,
    oosSharpe: ds.ml.overall.strategy_sharpe_ann,
    oosIc: ds.ml.overall.ic_pearson,
    synthetic: true,
  })
  console.error(`wrote ${file}: ${ds.bars} bars, ${Math.round(body.length / 1024)} KB`)
}
await writeFile(new URL('index.json', OUT), JSON.stringify({ generatedAt: '2026-07-11T00:00:00+00:00', synthetic: true, datasets }, null, 2) + '\n')
