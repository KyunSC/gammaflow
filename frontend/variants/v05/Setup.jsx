'use client'

import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, strategiesForPlane, FAMILIES, STRATEGIES } from '../../lib/backtest/strategies'
import { LIVE_SYMBOLS, LIVE_PERIODS, LIVE_INTERVALS } from '../../lib/backtest/datasets'
import { propSetup } from '../../lib/backtest/prop'
import { FIRMS, FIRM_LIST, SIZES, PROP_ASOF, resolvePlan } from '../../lib/backtest/prop/firms'
import { FUTURES_LIVE_SYMBOLS, contractsForSymbol } from '../../lib/backtest/prop/contracts'
import { fmtCompact } from '../../lib/backtest/format'

/**
 * Variant 05 copy of components/backtest/StrategyPanel.jsx. Same store calls
 * and the same schema-driven fields; restyled with sentence-case headings, no
 * step badges, labelled controls, and a visible marker on the parameter that
 * [ and ] will step.
 *
 * The left column: pick data, pick a strategy, tune it, run.
 *
 * Nothing here is hand-written per strategy. The parameter inputs are rendered
 * from `strategy.params`, which is the same schema the sweep axes and the
 * command palette read, so adding a knob to a strategy makes it appear in all
 * three places at once.
 *
 * Costs and exits start collapsed. The account section is always here;
 * switching it to a prop firm opens the advanced view, where the prop tab lives.
 */
export default function Setup() {
  return (
    <section id="v05-setup" aria-label="Setup" className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-auto px-3 pt-3 pb-4">
        <DatasetSection />
        <StrategySection />
        <div className="flex flex-col gap-3">
          <CostSection />
          <RiskSection />
        </div>
        <PropSection />
      </div>
      <RunBar />
    </section>
  )
}

function Section({ title, children, right }) {
  return (
    <div>
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className="v05-setup-h">{title}</h3>
        <span className="flex-1" />
        {right}
      </div>
      {children}
    </div>
  )
}

/** A section that starts closed, with its current settings readable in the summary. */
function Collapsible({ title, summary, children }) {
  return (
    <details className="v05-details">
      <summary className="flex items-baseline gap-2 hover:[&_h3]:text-amber">
        <span className="v05-caret w-2 text-[8px] text-dim" aria-hidden>▶</span>
        <h3 className="v05-setup-h shrink-0">{title}</h3>
        <span className="min-w-0 flex-1 truncate text-right font-mono text-[11px] text-muted">{summary}</span>
      </summary>
      <div className="mt-2 pl-4">{children}</div>
    </details>
  )
}

function Segmented({ value, onChange, options }) {
  return (
    <div className="grid grid-cols-2 gap-1">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`btn !px-1 !py-1 ${value === o.value ? 'btn-active' : ''}`}
          title={o.title}
          aria-pressed={value === o.value}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Switch({ checked, onChange, title, label }) {
  return <button role="switch" aria-checked={Boolean(checked)} aria-label={label || title} onClick={() => onChange(!checked)} className="switch" title={title} />
}

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

  const researchSets = researchIndex?.datasets || []
  const example = useBacktest((s) => s.example)
  const setExample = useBacktest((s) => s.setExample)
  const refreshDataset = useBacktest((s) => s.refreshDataset)
  const loading = useBacktest((s) => s.datasetLoading)
  const propOn = useBacktest((s) => s.prop.enabled)

  return (
    <Section title="Data">
      <Segmented
        value={plane}
        onChange={setPlane}
        options={[
          { value: 'research', label: 'historical + GEX', title: 'Published history with bar-aligned gamma levels and model predictions. Needed for Gamma and Model strategies.' },
          { value: 'live', label: 'live prices', title: 'OHLCV straight from /api/historical, any symbol and interval. No historical GEX: the gamma endpoint only returns the current snapshot.' },
        ]}
      />

      <div className="mt-1.5">
        {plane === 'live' ? (
          <div className="grid grid-cols-3 gap-1">
            <Select value={liveSymbol} onChange={(v) => setLive({ liveSymbol: v })} options={propOn ? FUTURES_LIVE_SYMBOLS : LIVE_SYMBOLS} label="Symbol" />
            <Select value={livePeriod} onChange={(v) => setLive({ livePeriod: v })} options={LIVE_PERIODS} label="Period" />
            <Select value={liveInterval} onChange={(v) => setLive({ liveInterval: v })} options={LIVE_INTERVALS} label="Interval" />
          </div>
        ) : (
          <Select
            value={researchSymbol}
            onChange={setResearchSymbol}
            label="Symbol"
            options={researchSets.length ? researchSets.map((d) => d.symbol) : ['QQQ', 'SPY']}
          />
        )}
      </div>

      <p className="v05-hint mt-1.5">
        {loading
          ? 'Loading…'
          : plane === 'research'
            ? `5-minute bars with bar-aligned gamma levels${example ? ', from the bundled sample' : ''}.`
            : 'Recent prices only. Gamma and Model strategies need the historical data.'}
      </p>

      {advanced && (
        <div className="mt-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            {plane === 'research' && (
              <label className="flex flex-1 items-center gap-2 text-[11px] text-muted">
                <input type="checkbox" checked={example} onChange={(e) => setExample(e.target.checked)} className="accent-amber" />
                Use bundled sample
              </label>
            )}
            <button className="btn !px-2 !py-0.5 !text-[10px]" disabled={loading} onClick={refreshDataset}>
              {loading ? 'loading…' : 'refresh'}
            </button>
          </div>
          {dataset && (
            <p className="v05-hint">
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
  // While a dataset loads, only the plane decides availability — otherwise
  // every research-only strategy would blink out until the bars arrive.
  const available = new Set(strategiesForPlane(plane, dataset ?? undefined).map((s) => s.id))
  const groups = FAMILIES.map((f) => ({
    label: f.label,
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
      right={
        <button onClick={resetParams} className="font-mono text-[11px] text-dim hover:text-ink" title="Reset parameters to defaults">
          reset params
        </button>
      }
    >
      <Select value={strategyId} onChange={setStrategy} groups={groups} label="Strategy" />
      <p className="v05-hint mt-1.5 mb-3">{strategy.blurb}</p>

      <div className="flex flex-col gap-2">
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
            className="btn mt-1 w-full"
          >
            open rule builder
          </button>
        )}
      </div>
    </Section>
  )
}

/** One row per schema entry. Number params also get `[` / `]` stepping when
 *  focused, which is how the keyboard-first param search works. */
function ParamField({ schema, value, onChange, focused, onFocus }) {
  const label = (
    <span className="w-[108px] shrink-0 truncate text-[12px] text-muted" title={schema.label}>
      {schema.label}
    </span>
  )

  if (schema.type === 'boolean') {
    return (
      <div className="flex items-center gap-2" onMouseDown={onFocus}>
        {label}
        <span className="flex-1" />
        <Switch checked={value} onChange={onChange} label={schema.label} />
      </div>
    )
  }

  if (schema.type === 'select') {
    return (
      <div className="flex items-center gap-2" onMouseDown={onFocus}>
        {label}
        <div className="flex-1">
          <Select value={value} onChange={onChange} options={schema.options} label={schema.label} />
        </div>
      </div>
    )
  }

  return (
    <div
      className={`-mx-1 flex items-center gap-2 px-1 py-0.5 ${focused ? 'bg-amber/6 shadow-[inset_2px_0_0_var(--color-amber)]' : ''}`}
      onMouseDown={onFocus}
      onFocus={onFocus}
      title={focused ? '[ and ] step this value' : undefined}
    >
      {label}
      <input
        type="range"
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`${schema.label} slider`}
        className="h-[3px] min-w-0 flex-1 cursor-pointer appearance-none rounded bg-hair-bright accent-amber"
      />
      <input
        type="number"
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={schema.label}
        className="field !w-[60px] shrink-0 !px-1 !py-0.5 text-right"
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
        <p className="v05-hint">
          Prop mode sizes in contracts: commission and slippage are set per contract under{' '}
          <span className="text-muted">account</span>, and capital is the account size.
        </p>
      </Collapsible>
    )
  }

  const summary = `${costs.slippageBps} bp · $${costs.commissionPerTrade}/fill · $${fmtCompact(costs.initialCapital)} · ${costs.sizePct}× equity`
  return (
    <Collapsible title="Costs & sizing" summary={summary}>
      <div className="flex flex-col gap-2">
        <NumRow
          label="Slippage (bp)"
          value={costs.slippageBps}
          min={0}
          max={20}
          step={0.5}
          onChange={(v) => setCosts({ slippageBps: v })}
          hint="Drag this up and watch the edge die — the single most honest control on the page."
        />
        <NumRow label="Commission ($)" value={costs.commissionPerTrade} min={0} max={10} step={0.1} onChange={(v) => setCosts({ commissionPerTrade: v })} />
        <NumRow label="Capital ($)" value={costs.initialCapital} min={1000} max={1000000} step={1000} onChange={(v) => setCosts({ initialCapital: v })} />
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
      <div className="flex flex-col gap-2">
        <NumRow label="Stop (%)" value={risk.stopPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ stopPct: v })} hint="0 disables" />
        <NumRow label="Target (%)" value={risk.targetPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ targetPct: v })} hint="0 disables" />
        <NumRow label="Max bars" value={risk.maxBars} min={0} max={200} step={1} onChange={(v) => setRisk({ maxBars: v })} hint="0 disables" />
        <div className="flex items-center gap-2">
          <span className="w-[108px] shrink-0 text-[12px] text-muted">Flat at close</span>
          <span className="flex-1" />
          {propOn ? (
            <span className="text-[10px] text-amber" title="Prop firms require no overnight positions">
              forced · 16:45 ET
            </span>
          ) : (
            <Switch checked={risk.flatAtSessionEnd} onChange={(v) => setRisk({ flatAtSessionEnd: v })} label="Flat at close" />
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="w-[108px] shrink-0 text-[12px] text-muted">Allow shorts</span>
          <span className="flex-1" />
          <Switch checked={risk.allowShort} onChange={(v) => setRisk({ allowShort: v })} label="Allow shorts" />
        </div>
      </div>
    </Collapsible>
  )
}

/** Footer of the setup column, outside its scroll area, so Run never scrolls out of reach on desktop. */
function RunBar() {
  const run = useBacktest((s) => s.run)
  const running = useBacktest((s) => s.running)
  const dataset = useBacktest((s) => s.dataset)
  const autoRun = useBacktest((s) => s.autoRun)
  const toggleAutoRun = useBacktest((s) => s.toggleAutoRun)

  return (
    <div className="v05-rule-t bg-canvas px-3 py-2.5">
      <button
        onClick={run}
        disabled={running || !dataset}
        className="btn btn-primary flex w-full items-center justify-center gap-2 !py-2 !text-[12px]"
        title="Run backtest (R)"
      >
        {running ? 'running…' : autoRun ? 'run again' : 'run backtest'}
        <span className="font-normal opacity-60">R</span>
      </button>
      <div className="mt-2 flex items-center gap-2 text-[11px] text-dim">
        <Switch checked={autoRun} onChange={toggleAutoRun} title="Re-run automatically when a setting changes" label="Re-run on every change" />
        <span>{autoRun ? 'Re-runs on every change' : 'Runs only when you press Run'}</span>
      </div>
    </div>
  )
}

/** Rule fields a user can override, in display order. `pct` values are
 *  stored as fractions and edited as percentages. */
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
    <Section title="Account" right={info?.plan?.overridden?.length ? <span className="font-mono text-[11px] text-amber">rules edited</span> : null}>
      <div className="mb-1.5 grid grid-cols-2 gap-1">
        <button onClick={() => setProp({ enabled: false })} aria-pressed={!prop.enabled} className={`btn ${!prop.enabled ? 'btn-active' : ''}`}>
          own capital
        </button>
        <button onClick={() => setProp({ enabled: true })} aria-pressed={prop.enabled} className={`btn ${prop.enabled ? 'btn-active' : ''}`} title="Futures only, under a prop firm's rules">
          prop firm
        </button>
      </div>

      {!prop.enabled ? (
        <p className="v05-hint">
          Prop mode trades NQ/ES futures in whole contracts under a firm&apos;s evaluation, drawdown and payout rules,
          and prices the account — some strategies only pay when the fee caps the downside.
        </p>
      ) : info.error ? (
        <p className="v05-hint !text-neg">{info.error}</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {FIRM_LIST.length > 1 && (
            <Select value={prop.firm} onChange={(v) => setProp({ firm: v })} options={FIRM_LIST.map((f) => ({ value: f.id, label: f.label }))} label="Firm" />
          )}
          <div className="grid grid-cols-4 gap-1">
            {plans.map((p) => (
              <button key={p.id} onClick={() => setProp({ plan: p.id })} className={`btn !px-1 text-[10px] ${prop.plan === p.id ? 'btn-active' : ''}`} title={p.blurb}>
                {p.label.replace(/^Lucid/, '')}
              </button>
            ))}
          </div>
          <p className="v05-hint">{firm.plans[prop.plan]?.blurb}</p>
          <span className="text-[12px] text-muted">Account size</span>
          <div className="grid grid-cols-4 gap-1">
            {SIZES.map((sz) => {
              const p = resolvePlan({ ...prop, size: sz.id })
              return (
                <button
                  key={sz.id}
                  onClick={() => setProp({ size: sz.id })}
                  className={`btn flex flex-col items-center !px-1 !py-1 ${prop.size === sz.id ? 'btn-active' : ''}`}
                  title={`${p.planLabel} ${sz.label}: max loss $${p.maxLoss.toLocaleString()}, up to ${p.maxMinis} minis / ${p.maxMinis * 10} micros`}
                >
                  <span className="text-[11px]">{sz.label}</span>
                  <span className="num text-[9px] text-dim">${(p.price + p.activationFee).toLocaleString()}</span>
                </button>
              )
            })}
          </div>
          <p className="v05-hint">
            {info.plan.hasEval && <>Target <span className="num text-muted">${info.plan.profitTarget.toLocaleString()}</span> · </>}
            Max loss <span className="num text-muted">${info.plan.maxLoss.toLocaleString()}</span> ·
            Daily <span className="num text-muted">{info.plan.dailyLossLimit ? `$${info.plan.dailyLossLimit.toLocaleString()}` : 'none'}</span> ·
            Up to <span className="num text-muted">{info.plan.maxMinis}</span> minis / <span className="num text-muted">{info.plan.maxMinis * 10}</span> micros
          </p>
          <div className="flex items-center gap-2">
            <span className="w-[108px] shrink-0 text-[12px] text-muted">Daily limit</span>
            <button onClick={() => setProp({ dll: !prop.dll })} className={`btn flex-1 !py-1 ${prop.dll ? 'btn-active' : ''}`}>
              {prop.dll ? (info.plan.dailyLossLimit ? `on · $${info.plan.dailyLossLimit.toLocaleString()}` : 'on · none at this size') : 'off'}
            </button>
          </div>
          <div className="flex items-baseline justify-between font-mono text-[11px]">
            <span className="text-muted">Account price</span>
            <span className="num text-ink">${(info.plan.price + info.plan.activationFee).toLocaleString()}</span>
          </div>

          <div className="flex items-center gap-2">
            <span className="w-[108px] shrink-0 text-[12px] text-muted">Contract</span>
            <div className="flex-1">
              <Select
                value={info.contract.id}
                onChange={(v) => setProp({ contract: v })}
                label="Contract"
                options={contractsForSymbol(symbol).map((c) => ({ value: c.id, label: c.label }))}
              />
            </div>
          </div>
          <NumRow label={`Qty (max ${info.limit})`} value={info.contracts} min={1} max={info.limit} step={1} onChange={(v) => setProp({ contracts: v })} />
          <NumRow label="Comm. $/side" value={prop.commissionPerSide} min={0} max={5} step={0.05} onChange={(v) => setProp({ commissionPerSide: v })} hint="Per contract, per side" />
          <NumRow label="Slippage (tk)" value={prop.slippageTicks} min={0} max={8} step={0.25} onChange={(v) => setProp({ slippageTicks: v })} hint="Ticks per fill (0.25 pt on NQ/ES)" />
          {info.proxy && (
            <div className="flex items-center gap-2" title="ETF bars are scaled by this ratio to price futures. Seeded from the latest GEX snapshot.">
              <span className="w-[108px] shrink-0 text-[12px] text-muted">
                {symbol}→{info.contract.family}
              </span>
              <input
                type="number"
                step={0.01}
                value={info.priceScale}
                onChange={(e) => setProp({ ratio: { ...prop.ratio, [symbol]: Number(e.target.value) } })}
                className="field flex-1 !px-1 !py-0.5 text-right"
              />
              <span className="font-mono text-[10px] text-amber">proxy</span>
            </div>
          )}

          <details className="mt-0.5">
            <summary className="cursor-pointer text-[12px] text-muted hover:text-ink">
              Firm rules {info.plan.overridden.length > 0 && `· ${info.plan.overridden.length} edited`}
            </summary>
            <div className="mt-1.5 flex flex-col gap-1">
              {RULE_FIELDS.filter((f) => !f.evalOnly || info.plan.hasEval).map((f) => {
                const raw = info.plan[f.key]
                const value = f.list ? raw?.[0] : raw
                const shown = value === null || value === undefined ? '' : f.pct ? Number((value * 100).toFixed(2)) : value
                const edited = info.plan.overridden.includes(f.key)
                return (
                  <label key={f.key} className="flex items-center gap-2">
                    <span className={`w-[108px] shrink-0 truncate text-[12px] ${edited ? 'text-amber' : 'text-muted'}`}>{f.label}</span>
                    <input
                      type="number"
                      value={shown}
                      placeholder="none"
                      onChange={(e) => {
                        const v = e.target.value === '' ? null : Number(e.target.value)
                        setPropOverride(f.key, v === null ? (f.key === 'dailyLossLimit' ? 0 : null) : f.pct ? v / 100 : f.list ? [v] : v)
                      }}
                      className="field flex-1 !px-1 !py-0.5 text-right"
                    />
                  </label>
                )
              })}
              <div className="flex items-center justify-between text-[11px] text-dim">
                <span>
                  Preset as of {PROP_ASOF}. Verify on{' '}
                  <a href={firm.url} target="_blank" rel="noreferrer" className="text-muted underline">
                    {firm.url.replace('https://', '')}
                  </a>
                </span>
                <button onClick={() => setProp({ overrides: {} })} className="hover:text-ink">
                  reset
                </button>
              </div>
            </div>
          </details>
        </div>
      )}
    </Section>
  )
}

function NumRow({ label, value, min, max, step, onChange, hint }) {
  return (
    <div className="flex items-center gap-2" title={hint}>
      <span className="w-[108px] shrink-0 truncate text-[12px] text-muted">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`${label} slider`}
        className="h-[3px] min-w-0 flex-1 cursor-pointer appearance-none rounded bg-hair-bright accent-amber"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
        className="field !w-[72px] shrink-0 !px-1 !py-0.5 text-right"
      />
    </div>
  )
}

/** `options` for a flat list, or `groups: [{ label, options }]` for <optgroup>s.
 *  Options may be strings or `{ value, label, disabled }`. */
export function Select({ value, onChange, options, groups, label }) {
  const norm = (list) => list.map((o) => (typeof o === 'string' ? { value: o, label: o } : o))
  const renderOpts = (list) =>
    norm(list).map((o) => (
      <option key={o.value} value={o.value} disabled={o.disabled} className="bg-panel text-ink">
        {o.label}
      </option>
    ))
  return (
    <div className="relative">
      <select value={value} onChange={(e) => onChange(e.target.value)} className="field cursor-pointer pr-5" aria-label={label}>
        {groups
          ? groups.map((g) => (
              <optgroup key={g.label} label={g.label} className="bg-panel text-dim">
                {renderOpts(g.options)}
              </optgroup>
            ))
          : renderOpts(options)}
      </select>
      <span className="pointer-events-none absolute top-1/2 right-1.5 -translate-y-1/2 text-[8px] text-dim">▼</span>
    </div>
  )
}
