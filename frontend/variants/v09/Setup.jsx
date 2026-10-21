'use client'

import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, strategiesForPlane, FAMILIES, STRATEGIES } from '../../lib/backtest/strategies'
import { LIVE_SYMBOLS, LIVE_PERIODS, LIVE_INTERVALS } from '../../lib/backtest/datasets'
import { propSetup } from '../../lib/backtest/prop'
import { FIRMS, FIRM_LIST, SIZES, PROP_ASOF, resolvePlan } from '../../lib/backtest/prop/firms'
import { FUTURES_LIVE_SYMBOLS, contractsForSymbol } from '../../lib/backtest/prop/contracts'
import { fmtCompact } from '../../lib/backtest/format'

/**
 * Setup column — same controls and store actions as the original
 * StrategyPanel, laid out as a form: sentence-case headings, one row per
 * setting, rules between sections instead of boxes. Costs start open because
 * they are part of every claim the result line makes.
 */
export default function Setup({ narrow }) {
  return (
    <div className={narrow ? 'flex flex-col' : 'flex h-full min-h-0 flex-col'}>
      <div className={`flex flex-col gap-5 px-4 py-4 ${narrow ? '' : 'min-h-0 flex-1 overflow-y-auto'}`}>
        <DatasetSection />
        <StrategySection />
        <CostSection />
        <RiskSection />
        <PropSection />
      </div>
      <RunBar />
    </div>
  )
}

function Section({ title, children, right, id }) {
  return (
    <section aria-labelledby={id}>
      <div className="mb-2 flex items-baseline gap-2">
        <h2 id={id} className="v9-h">{title}</h2>
        <span className="flex-1" />
        {right}
      </div>
      {children}
    </section>
  )
}

function Collapsible({ title, summary, children, open }) {
  return (
    <details className="v9-more" open={open}>
      <summary className="flex items-baseline gap-2">
        <span className="v9-caret" aria-hidden="true">▸</span>
        <span className="v9-h whitespace-nowrap">{title}</span>
        <span className="flex-1" />
        <span className="v9-num min-w-0 truncate text-[11px] text-dim">{summary}</span>
      </summary>
      <div className="mt-2.5">{children}</div>
    </details>
  )
}

function Seg({ value, onChange, options, label }) {
  return (
    <div className="v9-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)} title={o.title}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Toggle({ checked, onChange, title, children }) {
  return (
    <button type="button" role="switch" aria-checked={Boolean(checked)} onClick={() => onChange(!checked)} className="v9-toggle" title={title}>
      {children}
    </button>
  )
}

const Note = ({ children, tone = 'text-dim' }) => <p className={`mt-1.5 text-[11.5px] leading-snug ${tone}`}>{children}</p>

function DatasetSection() {
  const plane = useBacktest((s) => s.plane)
  const setPlane = useBacktest((s) => s.setPlane)
  const liveSymbol = useBacktest((s) => s.liveSymbol)
  const livePeriod = useBacktest((s) => s.livePeriod)
  const liveInterval = useBacktest((s) => s.liveInterval)
  const setLive = useBacktest((s) => s.setLive)
  const researchSymbol = useBacktest((s) => s.researchSymbol)
  const setResearchSymbol = useBacktest((s) => s.setResearchSymbol)
  const researchIndex = useBacktest((s) => s.researchIndex)
  const dataset = useBacktest((s) => s.dataset)
  const advanced = useBacktest((s) => s.advanced)
  const example = useBacktest((s) => s.example)
  const setExample = useBacktest((s) => s.setExample)
  const refreshDataset = useBacktest((s) => s.refreshDataset)
  const loading = useBacktest((s) => s.datasetLoading)
  const propOn = useBacktest((s) => s.prop.enabled)
  const researchSets = researchIndex?.datasets || []

  return (
    <Section title="Data" id="v9-h-data">
      <Seg
        label="Data source"
        value={plane}
        onChange={setPlane}
        options={[
          { value: 'research', label: 'History + GEX', title: 'Published history with bar-aligned gamma levels and model predictions. Needed for Gamma and Model strategies.' },
          { value: 'live', label: 'Live prices', title: 'OHLCV from /api/historical, any symbol and interval. No historical GEX: the gamma endpoint only returns the current snapshot.' },
        ]}
      />
      <div className="mt-2">
        {plane === 'live' ? (
          <div className="grid grid-cols-3 gap-1.5">
            <Select label="Symbol" value={liveSymbol} onChange={(v) => setLive({ liveSymbol: v })} options={propOn ? FUTURES_LIVE_SYMBOLS : LIVE_SYMBOLS} />
            <Select label="Period" value={livePeriod} onChange={(v) => setLive({ livePeriod: v })} options={LIVE_PERIODS} />
            <Select label="Interval" value={liveInterval} onChange={(v) => setLive({ liveInterval: v })} options={LIVE_INTERVALS} />
          </div>
        ) : (
          <Select
            label="Symbol"
            value={researchSymbol}
            onChange={setResearchSymbol}
            options={researchSets.length ? researchSets.map((d) => d.symbol) : ['QQQ', 'SPY']}
          />
        )}
      </div>
      <Note>
        {loading
          ? 'Loading…'
          : plane === 'research'
            ? `5-minute bars with gamma levels${example ? ', from the bundled sample' : ''}.`
            : 'Recent prices only. Gamma and Model strategies need historical data.'}
      </Note>

      {advanced && (
        <div className="mt-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-3">
            {plane === 'research' && (
              <Toggle checked={example} onChange={setExample} title="Use the QQQ/SPY sample bundled with the app instead of the server's published dataset">
                Bundled sample
              </Toggle>
            )}
            <span className="flex-1" />
            <button className="v9-btn" disabled={loading} onClick={refreshDataset}>
              {loading ? 'Loading…' : 'Reload'}
            </button>
          </div>
          {dataset && (
            <p className="text-[11px] leading-snug text-dim">
              {dataset.generatedAt && <>Generated {dataset.generatedAt.slice(0, 10)} · </>}
              {dataset.version && <>Version {dataset.version.slice(0, 8)} · </>}
              {(dataset.cached || researchIndex?.cached) && <>Offline cache (≤24h old) · </>}
              {dataset.quality?.predictionValidation === 'legacy-unverified' && <>Legacy model predictions; training overlap unverified. · </>}
              {dataset.plane === 'live' && <>Exploratory snapshot; shared links reload current history. · </>}
              {dataset.plane === 'research' && dataset.ml && <>Model: {dataset.ml.model}, {dataset.ml.horizon}</>}
            </p>
          )}
        </div>
      )}
    </Section>
  )
}

function StrategySection() {
  const plane = useBacktest((s) => s.plane)
  const dataset = useBacktest((s) => s.dataset)
  const strategyId = useBacktest((s) => s.strategyId)
  const setStrategy = useBacktest((s) => s.setStrategy)
  const params = useBacktest((s) => s.paramsByStrategy[s.strategyId])
  const setParam = useBacktest((s) => s.setParam)
  const resetParams = useBacktest((s) => s.resetParams)
  const focusedParam = useBacktest((s) => s.focusedParam)
  const setFocusedParam = useBacktest((s) => s.setFocusedParam)
  const setTab = useBacktest((s) => s.setTab)
  const setAdvanced = useBacktest((s) => s.setAdvanced)

  const strategy = getStrategy(strategyId)
  const available = new Set(strategiesForPlane(plane, dataset ?? undefined).map((s) => s.id))
  const groups = FAMILIES.map((f) => ({
    label: `${f.label} (Alt+${f.hotkey})`,
    options: STRATEGIES.filter((s) => s.family === f.id).map((s) => ({
      value: s.id,
      label: available.has(s.id) ? s.label : `${s.label} (${s.plane === 'research' && plane !== 'research' ? 'needs historical data' : 'not in this dataset'})`,
      disabled: !available.has(s.id),
    })),
  })).filter((g) => g.options.length)

  const schema = strategy.params.filter((p) => !p.hidden)

  return (
    <Section
      title="Strategy"
      id="v9-h-strategy"
      right={
        <button onClick={resetParams} className="text-[11.5px] text-dim hover:text-ink" title="Reset parameters to defaults">
          Reset to defaults
        </button>
      }
    >
      <Select label="Strategy" value={strategyId} onChange={setStrategy} groups={groups} />
      <Note>{strategy.blurb}</Note>

      <div className="mt-3 flex flex-col gap-1.5">
        {schema.map((p) => (
          <ParamField
            key={p.key}
            schema={p}
            value={params?.[p.key]}
            focused={focusedParam === p.key}
            onFocus={() => setFocusedParam(p.key)}
            onChange={(v) => setParam(p.key, v)}
          />
        ))}
        {strategyId === 'custom' && (
          <button
            onClick={() => {
              setAdvanced(true)
              setTab('rules')
            }}
            className="v9-btn mt-1 justify-center"
          >
            Open the rule builder
          </button>
        )}
      </div>
      {schema.some((p) => p.type === 'number') && (
        <p className="mt-2 text-[11px] text-dim">
          Click a parameter, then <span className="v9-kbd">[</span> <span className="v9-kbd">]</span> to step it.
        </p>
      )}
    </Section>
  )
}

const ROW = 'grid grid-cols-[minmax(0,104px)_minmax(0,1fr)_64px] items-center gap-2'

function ParamField({ schema, value, onChange, focused, onFocus }) {
  const label = (
    <span className={`truncate text-[12px] ${focused ? 'text-ink' : 'text-muted'}`} title={schema.label}>
      {schema.label}
    </span>
  )

  if (schema.type === 'boolean') {
    return (
      <div className="flex items-center py-0.5" onMouseDown={onFocus}>
        <Toggle checked={value} onChange={onChange}>{schema.label}</Toggle>
      </div>
    )
  }

  if (schema.type === 'select') {
    return (
      <div className="grid grid-cols-[minmax(0,104px)_minmax(0,1fr)] items-center gap-2" onMouseDown={onFocus}>
        {label}
        <Select label={schema.label} value={value} onChange={onChange} options={schema.options} />
      </div>
    )
  }

  return (
    <div
      className={`${ROW} -mx-2 border-l-2 px-2 ${focused ? 'border-amber' : 'border-transparent'}`}
      onMouseDown={onFocus}
      onFocusCapture={onFocus}
    >
      {label}
      <input
        type="range"
        aria-label={schema.label}
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        className="v9-range min-w-0"
      />
      <input
        type="number"
        aria-label={`${schema.label} value`}
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        className="v9-field !px-1 !py-0.5 text-right"
      />
    </div>
  )
}

function CostSection() {
  const costs = useBacktest((s) => s.costs)
  const setCosts = useBacktest((s) => s.setCosts)
  const propOn = useBacktest((s) => s.prop.enabled)

  if (propOn) {
    return (
      <Collapsible title="Costs & sizing" summary="per contract">
        <p className="text-[11.5px] leading-snug text-dim">
          Prop mode sizes in contracts: commission and slippage are set per contract under Account, and capital is the
          account size.
        </p>
      </Collapsible>
    )
  }

  const summary = `${costs.slippageBps} bp · $${costs.commissionPerTrade} · $${fmtCompact(costs.initialCapital)} · ${costs.sizePct}×`
  return (
    <Collapsible title="Costs & sizing" summary={summary} open>
      <div className="flex flex-col gap-1.5">
        <NumRow label="Slippage (bp)" value={costs.slippageBps} min={0} max={20} step={0.5} onChange={(v) => setCosts({ slippageBps: v })} />
        <p className="text-[11px] leading-snug text-dim">Raise slippage and see whether the edge survives. Most intraday edges don&apos;t.</p>
        <NumRow label="Commission ($)" value={costs.commissionPerTrade} min={0} max={10} step={0.1} onChange={(v) => setCosts({ commissionPerTrade: v })} />
        <NumRow label="Capital ($)" value={costs.initialCapital} min={1000} max={1000000} step={1000} onChange={(v) => setCosts({ initialCapital: v })} wide />
        <NumRow label="Size (× equity)" value={costs.sizePct} min={0.1} max={3} step={0.1} onChange={(v) => setCosts({ sizePct: v })} />
      </div>
    </Collapsible>
  )
}

function RiskSection() {
  const risk = useBacktest((s) => s.risk)
  const setRisk = useBacktest((s) => s.setRisk)
  const propOn = useBacktest((s) => s.prop.enabled)

  const flat = propOn || risk.flatAtSessionEnd
  const summary = [
    risk.stopPct ? `stop ${risk.stopPct}%` : null,
    risk.targetPct ? `target ${risk.targetPct}%` : null,
    risk.maxBars ? `${risk.maxBars} bars` : null,
    flat ? 'flat at close' : null,
    risk.allowShort ? null : 'long only',
  ].filter(Boolean).join(' · ') || 'strategy exits only'

  return (
    <Collapsible title="Exits" summary={summary}>
      <div className="flex flex-col gap-1.5">
        <NumRow label="Stop (%)" value={risk.stopPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ stopPct: v })} />
        <NumRow label="Target (%)" value={risk.targetPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ targetPct: v })} />
        <NumRow label="Max bars" value={risk.maxBars} min={0} max={200} step={1} onChange={(v) => setRisk({ maxBars: v })} />
        <p className="text-[11px] text-dim">0 turns a limit off.</p>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 pt-1">
          {propOn ? (
            <span className="text-[12px] text-amber" title="Prop firms require no overnight positions">Flat at close: forced, 16:45 ET</span>
          ) : (
            <Toggle checked={risk.flatAtSessionEnd} onChange={(v) => setRisk({ flatAtSessionEnd: v })}>Flat at close</Toggle>
          )}
          <Toggle checked={risk.allowShort} onChange={(v) => setRisk({ allowShort: v })}>Allow shorts</Toggle>
        </div>
      </div>
    </Collapsible>
  )
}

function RunBar() {
  const run = useBacktest((s) => s.run)
  const running = useBacktest((s) => s.running)
  const dataset = useBacktest((s) => s.dataset)
  const autoRun = useBacktest((s) => s.autoRun)
  const toggleAutoRun = useBacktest((s) => s.toggleAutoRun)
  const lastRunMs = useBacktest((s) => s.lastRunMs)
  const runCount = useBacktest((s) => s.runCount)

  return (
    <div className="shrink-0 border-t border-hair px-4 py-3">
      <button onClick={run} disabled={running || !dataset} className="v9-run" title="Run backtest (R)">
        {running ? 'Running…' : autoRun ? 'Run again' : 'Run backtest'}
        <span className="v9-kbd !border-[#0b0c0e]/30 !text-[#0b0c0e]/70">R</span>
      </button>
      <div className="mt-2 flex items-center gap-2">
        <Toggle checked={autoRun} onChange={toggleAutoRun} title="Re-run automatically when a setting changes">
          Re-run on every change
        </Toggle>
        <span className="flex-1" />
        {runCount > 0 && !running && <span className="v9-num text-[11px] text-dim" title="Time the last run took">{lastRunMs.toFixed(0)} ms</span>}
      </div>
    </div>
  )
}

const RULE_FIELDS = [
  { key: 'price', label: 'Price ($)' },
  { key: 'activationFee', label: 'Activation ($)' },
  { key: 'profitTarget', label: 'Eval target ($)', evalOnly: true },
  { key: 'evalConsistency', label: 'Eval consist. %', pct: true, evalOnly: true },
  { key: 'maxLoss', label: 'Max loss ($)' },
  { key: 'dailyLossLimit', label: 'Daily limit ($)' },
  { key: 'maxMinis', label: 'Max minis' },
  { key: 'fundedConsistency', label: 'Funded cons. %', pct: true },
  { key: 'buffer', label: 'Buffer ($)' },
  { key: 'minDayProfit', label: 'Min day ($)' },
  { key: 'payoutCap', label: 'Payout cap ($)', list: true },
  { key: 'split', label: 'Split %', pct: true },
  { key: 'maxPayouts', label: 'Payouts → live' },
]

function PropSection() {
  const prop = useBacktest((s) => s.prop)
  const setProp = useBacktest((s) => s.setProp)
  const setPropOverride = useBacktest((s) => s.setPropOverride)
  const dataset = useBacktest((s) => s.dataset)
  const costs = useBacktest((s) => s.costs)
  const risk = useBacktest((s) => s.risk)
  const plane = useBacktest((s) => s.plane)
  const liveSymbol = useBacktest((s) => s.liveSymbol)
  const researchSymbol = useBacktest((s) => s.researchSymbol)

  const symbol = dataset?.symbol ?? (plane === 'live' ? liveSymbol : researchSymbol)
  const info = prop.enabled ? propSetup({ prop, symbol, costs, risk }) : null
  const firm = FIRMS[prop.firm] || FIRM_LIST[0]
  const plans = Object.values(firm.plans)

  return (
    <Section title="Account" id="v9-h-account" right={info?.plan?.overridden?.length ? <span className="text-[11px] text-amber">rules edited</span> : null}>
      <Seg
        label="Account type"
        value={prop.enabled ? 'prop' : 'cash'}
        onChange={(v) => setProp({ enabled: v === 'prop' })}
        options={[
          { value: 'cash', label: 'Own capital' },
          { value: 'prop', label: 'Prop firm', title: 'Futures only, under a prop firm’s rules' },
        ]}
      />

      {!prop.enabled ? (
        <Note>
          Prop mode trades NQ/ES futures in whole contracts under a firm&apos;s evaluation, drawdown and payout rules, and
          prices the account. Some strategies only pay when the fee caps the downside.
        </Note>
      ) : info.error ? (
        <Note tone="text-neg">{info.error}</Note>
      ) : (
        <div className="mt-2 flex flex-col gap-2">
          {FIRM_LIST.length > 1 && (
            <Select label="Firm" value={prop.firm} onChange={(v) => setProp({ firm: v })} options={FIRM_LIST.map((f) => ({ value: f.id, label: f.label }))} />
          )}
          <Seg label="Plan" value={prop.plan} onChange={(v) => setProp({ plan: v })} options={plans.map((p) => ({ value: p.id, label: p.label.replace(/^Lucid/, ''), title: p.blurb }))} />
          <p className="text-[11.5px] leading-snug text-dim">{firm.plans[prop.plan]?.blurb}</p>
          <span className="text-[12px] text-muted">Account size</span>
          <div className="v9-seg" role="group" aria-label="Account size">
            {SIZES.map((sz) => {
              const p = resolvePlan({ ...prop, size: sz.id })
              return (
                <button
                  key={sz.id}
                  type="button"
                  aria-pressed={prop.size === sz.id}
                  onClick={() => setProp({ size: sz.id })}
                  className="flex flex-col items-center !py-1"
                  title={`${p.planLabel} ${sz.label}: max loss $${p.maxLoss.toLocaleString()}, up to ${p.maxMinis} minis / ${p.maxMinis * 10} micros`}
                >
                  <span>{sz.label}</span>
                  <span className="v9-num text-[10.5px] opacity-75">${(p.price + p.activationFee).toLocaleString()}</span>
                </button>
              )
            })}
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[12px]">
            {info.plan.hasEval && (
              <>
                <dt className="text-dim">Eval target</dt>
                <dd className="v9-num text-right text-muted">${info.plan.profitTarget.toLocaleString()}</dd>
              </>
            )}
            <dt className="text-dim">Max loss</dt>
            <dd className="v9-num text-right text-muted">${info.plan.maxLoss.toLocaleString()}</dd>
            <dt className="text-dim">Contracts</dt>
            <dd className="v9-num text-right text-muted">{info.plan.maxMinis} minis / {info.plan.maxMinis * 10} micros</dd>
            <dt className="text-dim">Account price</dt>
            <dd className="v9-num text-right text-ink">${(info.plan.price + info.plan.activationFee).toLocaleString()}</dd>
          </dl>
          <Toggle checked={prop.dll} onChange={(v) => setProp({ dll: v })}>
            Daily loss limit {prop.dll ? (info.plan.dailyLossLimit ? `($${info.plan.dailyLossLimit.toLocaleString()})` : '(none at this size)') : 'off'}
          </Toggle>

          <div className="grid grid-cols-[minmax(0,104px)_minmax(0,1fr)] items-center gap-2">
            <span className="text-[12px] text-muted">Contract</span>
            <Select label="Contract" value={info.contract.id} onChange={(v) => setProp({ contract: v })} options={contractsForSymbol(symbol).map((c) => ({ value: c.id, label: c.label }))} />
          </div>
          <NumRow label={`Qty (max ${info.limit})`} value={info.contracts} min={1} max={info.limit} step={1} onChange={(v) => setProp({ contracts: v })} />
          <NumRow label="Comm. $/side" value={prop.commissionPerSide} min={0} max={5} step={0.05} onChange={(v) => setProp({ commissionPerSide: v })} />
          <NumRow label="Slippage (ticks)" value={prop.slippageTicks} min={0} max={8} step={0.25} onChange={(v) => setProp({ slippageTicks: v })} />
          <p className="text-[11px] text-dim">Commission per contract per side; slippage in ticks per fill (0.25 pt on NQ/ES).</p>
          {info.proxy && (
            <div className="grid grid-cols-[minmax(0,104px)_minmax(0,1fr)] items-center gap-2" title="ETF bars are scaled by this ratio to price futures. Seeded from the latest GEX snapshot.">
              <span className="text-[12px] text-muted">{symbol} → {info.contract.family}</span>
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  aria-label={`${symbol} to ${info.contract.family} price ratio`}
                  step={0.01}
                  value={info.priceScale}
                  onChange={(e) => setProp({ ratio: { ...prop.ratio, [symbol]: Number(e.target.value) } })}
                  className="v9-field !px-1 !py-0.5 text-right"
                />
                <span className="text-[11px] text-amber">proxy</span>
              </span>
            </div>
          )}

          <details className="v9-more">
            <summary className="flex items-baseline gap-2 text-[12px] text-muted">
              <span className="v9-caret" aria-hidden="true">▸</span>
              Firm rules {info.plan.overridden.length > 0 && `· ${info.plan.overridden.length} edited`}
            </summary>
            <div className="mt-1.5 flex flex-col gap-1">
              {RULE_FIELDS.filter((f) => !f.evalOnly || info.plan.hasEval).map((f) => {
                const raw = info.plan[f.key]
                const value = f.list ? raw?.[0] : raw
                const shown = value === null || value === undefined ? '' : f.pct ? Number((value * 100).toFixed(2)) : value
                const edited = info.plan.overridden.includes(f.key)
                return (
                  <label key={f.key} className="grid grid-cols-[minmax(0,104px)_minmax(0,1fr)] items-center gap-2">
                    <span className={`truncate text-[12px] ${edited ? 'text-amber' : 'text-muted'}`}>{f.label}</span>
                    <input
                      type="number"
                      value={shown}
                      placeholder="none"
                      onChange={(e) => {
                        const v = e.target.value === '' ? null : Number(e.target.value)
                        setPropOverride(f.key, v === null ? (f.key === 'dailyLossLimit' ? 0 : null) : f.pct ? v / 100 : f.list ? [v] : v)
                      }}
                      className="v9-field !px-1 !py-0.5 text-right"
                    />
                  </label>
                )
              })}
              <div className="flex items-baseline justify-between gap-2 text-[11px] text-dim">
                <span>
                  Preset as of {PROP_ASOF}. Check{' '}
                  <a href={firm.url} target="_blank" rel="noreferrer" className="v9-link">
                    {firm.url.replace('https://', '')}
                  </a>
                </span>
                <button onClick={() => setProp({ overrides: {} })} className="hover:text-ink">Reset</button>
              </div>
            </div>
          </details>
        </div>
      )}
    </Section>
  )
}

function NumRow({ label, value, min, max, step, onChange, wide }) {
  return (
    <div className={wide ? 'grid grid-cols-[minmax(0,104px)_minmax(0,1fr)_84px] items-center gap-2' : ROW}>
      <span className="truncate text-[12px] text-muted">{label}</span>
      <input type="range" aria-label={label} min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="v9-range min-w-0" />
      <input
        type="number"
        aria-label={`${label} value`}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="v9-field !px-1 !py-0.5 text-right"
      />
    </div>
  )
}

/** `options` for a flat list, or `groups: [{ label, options }]` for <optgroup>s. */
export function Select({ value, onChange, options, groups, label }) {
  const norm = (list) => list.map((o) => (typeof o === 'string' ? { value: o, label: o } : o))
  const renderOpts = (list) =>
    norm(list).map((o) => (
      <option key={o.value} value={o.value} disabled={o.disabled} className="bg-panel text-ink">
        {o.label}
      </option>
    ))
  return (
    <div className="relative min-w-0">
      <select value={value} aria-label={label} onChange={(e) => onChange(e.target.value)} className="v9-field cursor-pointer truncate pr-5">
        {groups
          ? groups.map((g) => (
              <optgroup key={g.label} label={g.label} className="bg-panel text-dim">
                {renderOpts(g.options)}
              </optgroup>
            ))
          : renderOpts(options)}
      </select>
      <span className="pointer-events-none absolute top-1/2 right-1.5 -translate-y-1/2 text-[9px] text-dim" aria-hidden="true">▼</span>
    </div>
  )
}
