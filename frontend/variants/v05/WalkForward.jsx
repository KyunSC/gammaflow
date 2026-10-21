'use client'

import { useBacktest } from '../../lib/backtest/store'
import { getStrategy } from '../../lib/backtest/strategies'
import { fmtSigned, fmtPct, fmtDate, fmtParam, signClass } from '../../lib/backtest/format'
import { EmptyState } from '../../components/backtest/Panel'

/**
 * Variant 05 copy of components/backtest/WalkForwardPanel.jsx. Same run and
 * the same numbers; the per-fold bordered cards are now rows of one table,
 * with in-sample greyed and out-of-sample coloured side by side.
 *
 * Expanding-window walk-forward, laid out the way `functions/ml/eval.py` folds
 * are structured: fold k trains on everything before its test slice.
 *
 * Each fold optimises the sweep axes in-sample and then trades the winner
 * out-of-sample. The IS-vs-OOS gap per fold is the headline: a strategy whose
 * in-sample Sharpe is 3 and whose out-of-sample Sharpe is 0 has been fitted to
 * noise, and no amount of curve-drawing elsewhere in this terminal changes that.
 */
export default function WalkForward() {
  const wf = useBacktest((s) => s.wf)
  const runWalkForward = useBacktest((s) => s.runWalkForward)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const sweep = useBacktest((s) => s.sweep)
  const schema = getStrategy(strategyId).params

  const modelFolds = dataset?.ml?.folds

  return (
    <div className="flex h-full flex-col">
      <div className="hair-b flex flex-wrap items-center gap-2 bg-panel-2 px-2 py-1.5 font-mono text-[10px] text-dim">
        <span>
          5 expanding folds · optimising{' '}
          <span className="text-muted">{labelFor(schema, sweep.xKey)}</span>
          {sweep.yKey && sweep.yKey !== sweep.xKey && (
            <>
              {' '}× <span className="text-muted">{labelFor(schema, sweep.yKey)}</span>
            </>
          )}{' '}
          in-sample
        </span>
        <button onClick={runWalkForward} disabled={wf.running} className="btn ml-auto">
          {wf.running ? `fold ${Math.round(wf.progress * 5)}/5` : 'run walk-forward'}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {wf.error ? (
          <EmptyState>{wf.error}</EmptyState>
        ) : !wf.data ? (
          <EmptyState>
            Fit the parameters on each fold&apos;s history, trade them on the fold that follows, and
            stitch the out-of-sample pieces together. It is the only number here that was not chosen
            with hindsight.
          </EmptyState>
        ) : (
          <FoldTable wf={wf.data} dataset={dataset} schema={schema} />
        )}

        {modelFolds && (
          <div className="hair-t p-2">
            <p className="mb-1.5 font-mono text-[9px] tracking-[0.12em] text-dim uppercase">
              model folds (exported from the ML harness)
            </p>
            <div className="flex flex-col gap-1">
              {modelFolds.map((f) => (
                <div key={f.fold} className="flex items-center gap-2 font-mono text-[10px]">
                  <span className="w-8 text-dim">f{f.fold}</span>
                  <FoldBar trainFrac={f.nTrain / (f.nTrain + f.nTest)} />
                  <span className="w-24 text-right text-dim">
                    IC <span className={signClass(f.oosIc)}>{fmtSigned(f.oosIc, 4)}</span>
                  </span>
                  <span className="w-28 text-right text-dim">
                    Sharpe <span className={signClass(f.oosSharpe)}>{fmtSigned(f.oosSharpe)}</span>
                  </span>
                  <span className="w-20 text-right text-dim">{(f.oosDirAcc * 100).toFixed(1)}% dir</span>
                </div>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] leading-snug text-dim">
              These are the random forest&apos;s own folds, computed by{' '}
              <span className="text-muted">export_backtest_data.py</span> — the per-fold IC swings sign,
              which is what a three-month sample of a weak signal is supposed to look like.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function FoldTable({ wf, dataset, schema }) {
  const worst = Math.min(...wf.folds.map((f) => f.oosSharpe))
  const best = Math.max(...wf.folds.map((f) => Math.max(f.isSharpe, f.oosSharpe)))
  const span = Math.max(Math.abs(worst), Math.abs(best), 1)

  return (
    <div className="p-2">
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px]">
        <Stat label="avg IS Sharpe" value={fmtSigned(wf.avgIsSharpe)} tone="text-dim" />
        <Stat label="avg OOS Sharpe" value={fmtSigned(wf.avgOosSharpe)} tone={signClass(wf.avgOosSharpe)} />
        <Stat
          label="degradation"
          value={fmtSigned(-wf.degradation)}
          tone={wf.degradation > 1 ? 'text-neg' : 'text-muted'}
          title="OOS minus IS. A large negative number is the signature of fitting the training window."
        />
        <Stat label="folds positive" value={`${wf.positiveFolds}/${wf.folds.length}`} tone={wf.positiveFolds > wf.folds.length / 2 ? 'text-pos' : 'text-neg'} />
        <Stat label="stitched OOS return" value={fmtPct(wf.totalReturn)} tone={signClass(wf.totalReturn)} />
        <Stat label="trials / fold" value={wf.trialsPerFold} tone="text-dim" />
        <Stat
          label="embargo"
          value={`${wf.embargoBars} bars`}
          tone="text-dim"
          title="Bars skipped between each training window and its test slice."
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] font-mono text-[11px]">
          <thead>
            <tr className="v05-colhead v05-rule-b">
              <th className="py-1 pr-2 text-left font-normal">fold</th>
              <th className="py-1 pr-2 text-left font-normal">test window</th>
              <th className="w-[18%] py-1 pr-2 text-left font-normal" title="train ▸ test split">train ▸ test</th>
              <th className="py-1 pr-2 text-right font-normal" title="In-sample Sharpe (greyed on purpose)">IS sharpe</th>
              <th className="py-1 pr-2 text-right font-normal">OOS sharpe</th>
              <th className="w-[16%] py-1 pr-2 font-normal" title="Grey: in-sample. Coloured: out-of-sample">IS / OOS</th>
              <th className="py-1 pr-2 text-right font-normal">trades</th>
              <th className="py-1 pr-2 text-right font-normal">OOS ret</th>
              <th className="py-1 text-left font-normal">chosen params</th>
            </tr>
          </thead>
          <tbody>
            {wf.folds.map((f) => (
              <tr key={f.fold} className="v05-rule-b">
                <td className="py-1 pr-2 text-dim">f{f.fold}</td>
                <td className="py-1 pr-2 whitespace-nowrap text-muted">
                  {fmtDate(dataset.time[f.testStart])} → {fmtDate(dataset.time[f.testEnd])}
                </td>
                <td className="py-1 pr-2"><FoldBar trainFrac={f.nTrain / (f.nTrain + f.nTest)} /></td>
                <td className="py-1 pr-2 text-right text-dim">{fmtSigned(f.isSharpe)}</td>
                <td className={`py-1 pr-2 text-right ${signClass(f.oosSharpe)}`}>{fmtSigned(f.oosSharpe)}</td>
                <td className="py-1 pr-2">
                  <span className="flex flex-col gap-0.5">
                    <SharpeBar value={f.isSharpe} span={span} dim />
                    <SharpeBar value={f.oosSharpe} span={span} />
                  </span>
                </td>
                <td className="py-1 pr-2 text-right text-dim">{f.oosTrades}</td>
                <td className={`py-1 pr-2 text-right ${signClass(f.oosReturn)}`}>{fmtPct(f.oosReturn)}</td>
                <td className="max-w-[220px] truncate py-1 text-[10.5px] text-dim">
                  {Object.entries(f.params)
                    .filter(([k, v]) => typeof v === 'number' && labelFor(schema, k) !== k)
                    .map(([k, v]) => `${labelFor(schema, k)}=${fmtParam(v)}`)
                    .join(' · ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-[11px] leading-snug text-dim">
        Grey bars are in-sample, coloured bars out-of-sample. The stitched OOS curve is overlaid on the
        equity panel in violet.
      </p>
    </div>
  )
}

function FoldBar({ trainFrac }) {
  return (
    <span className="flex h-2 w-full min-w-[60px] flex-1 overflow-hidden bg-panel-3" title="train ▸ test split">
      <span className="h-full bg-hair-bright" style={{ width: `${trainFrac * 100}%` }} />
      <span className="h-full bg-amber-dim" style={{ width: `${(1 - trainFrac) * 100}%` }} />
    </span>
  )
}

function SharpeBar({ value, span, dim }) {
  const pct = Math.min(1, Math.abs(value) / span) * 50
  const positive = value >= 0
  return (
    <span className="relative block h-1.5 w-full min-w-[60px] flex-1 bg-panel-3">
      <span className="absolute top-0 bottom-0 left-1/2 w-px bg-hair-bright" />
      <span
        className={`absolute top-0 bottom-0 ${dim ? 'opacity-40' : ''} ${positive ? 'bg-pos' : 'bg-neg'}`}
        style={positive ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` }}
      />
    </span>
  )
}

function Stat({ label, value, tone, title }) {
  return (
    <span className="flex items-baseline gap-1" title={title}>
      <span className="text-dim">{label}</span>
      <span className={`num ${tone || 'text-ink'}`}>{value}</span>
    </span>
  )
}

const labelFor = (schema, key) => schema.find((p) => p.key === key)?.label || key
