'use client'

import { useId } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy, strategiesForPlane, FAMILIES, STRATEGIES } from '../../../lib/backtest/strategies'
import { LIVE_SYMBOLS, LIVE_PERIODS, LIVE_INTERVALS } from '../../../lib/backtest/datasets'
import { propSetup } from '../../../lib/backtest/prop'
import { FIRMS, FIRM_LIST, SIZES, PROP_ASOF, resolvePlan } from '../../../lib/backtest/prop/firms'
import { FUTURES_LIVE_SYMBOLS, contractsForSymbol } from '../../../lib/backtest/prop/contracts'
import { fmtCompact } from '../../../lib/backtest/format'
import { Switch, Heading } from './ui'

/**
 * Setup rail: data, strategy and its parameters, costs, exits, account, Run.
 * Same controls and store actions as components/backtest/StrategyPanel.jsx;
 * the inputs are still generated from each strategy's `params` schema.
 * Laid out as a labelled form: no step badges, labels that wrap instead of
 * truncating, and every control has an accessible name.
 */
export default function Setup() {
  return (
    <div className="v7-setup">
      <div className="v7-setup-scroll">
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

function Section({ title, right, children }) {
  const id = useId()
  return (
    <section className="v7-setup-sec" aria-labelledby={id}>
      <Heading id={id} right={right}>{title}</Heading>
      {children}
    </section>
  )
}

function Fold({ title, summary, children }) {
  return (
    <details className="v7-fold">
      <summary>
        <span className="v7-fold-title">{title}</span>
        <span className="v7-fold-sum">{summary}</span>
      </summary>
      <div className="v7-fold-body">{children}</div>
    </details>
  )
}

function Choice({ value, onChange, options, label }) {
  return (
    <div className="v7-seg v7-seg-full" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)} title={o.title}>
          {o.label}
        </button>
      ))}
    </div>
  )
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
      <Choice
        label="Data source"
        value={plane}
        onChange={setPlane}
        options={[
          { value: 'research', label: 'Historical + GEX', title: 'Published history with bar-aligned gamma levels and model predictions. Needed for Gamma and Model strategies.' },
          { value: 'live', label: 'Live prices', title: 'OHLCV from /api/historical, any symbol and interval. No historical GEX: the gamma endpoint only returns the current snapshot.' },
        ]}
      />
      {plane === 'live' ? (
        <div className="v7-grid3">
          <Field label="Symbol"><Select value={liveSymbol} onChange={(v) => setLive({ liveSymbol: v })} options={propOn ? FUTURES_LIVE_SYMBOLS : LIVE_SYMBOLS} /></Field>
          <Field label="Period"><Select value={livePeriod} onChange={(v) => setLive({ livePeriod: v })} options={LIVE_PERIODS} /></Field>
          <Field label="Interval"><Select value={liveInterval} onChange={(v) => setLive({ liveInterval: v })} options={LIVE_INTERVALS} /></Field>
        </div>
      ) : (
        <Field label="Symbol" row>
          <Select value={researchSymbol} onChange={setResearchSymbol} options={researchSets.length ? researchSets.map((d) => d.symbol) : ['QQQ', 'SPY']} />
        </Field>
      )}
      <p className="v7-hint">
        {loading
          ? 'Loading…'
          : plane === 'research'
            ? `5-minute bars with gamma levels${example ? ', from the bundled sample' : ''}.`
            : 'Recent prices only. Gamma and Model strategies need historical data.'}
      </p>

      {advanced && (
        <div className="v7-stack">
          <div className="v7-line">
            {plane === 'research' && (
              <label className="v7-check">
                <input type="checkbox" checked={example} onChange={(e) => setExample(e.target.checked)} />
                Use bundled sample
              </label>
            )}
            <button type="button" className="btn" disabled={loading} onClick={refreshDataset}>
              {loading ? 'Loading…' : 'Reload data'}
            </button>
          </div>
          {dataset && (
            <p className="v7-hint">
              {dataset.generatedAt && <>Generated {dataset.generatedAt.slice(0, 10)}. </>}
              {dataset.version && <>Version {dataset.version.slice(0, 8)}. </>}
              {(dataset.cached || researchIndex?.cached) && <>Offline cache (up to 24 h old). </>}
              {dataset.quality?.predictionValidation === 'legacy-unverified' && <>Legacy model predictions; training overlap unverified. </>}
              {dataset.plane === 'live' && <>Exploratory snapshot; shared links reload current history. </>}
              {dataset.plane === 'research' && dataset.ml && <>Model: {dataset.ml.model}, {dataset.ml.horizon}.</>}
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
    label: `${f.label} (Alt ${f.hotkey})`,
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
      right={<button type="button" onClick={resetParams} className="v7-link" title="Reset parameters to their defaults">Reset</button>}
    >
      <Select value={strategyId} onChange={setStrategy} groups={groups} label="Strategy" />
      <p className="v7-hint v7-blurb">{strategy.blurb}</p>
      <div className="v7-stack">
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
          <button type="button" onClick={() => { setAdvanced(true); setTab('rules') }} className="btn">
            Open rule builder
          </button>
        )}
      </div>
      {schema.some((p) => p.type === 'number') && (
        <p className="v7-hint">Click a parameter, then <kbd>[</kbd> <kbd>]</kbd> step it.</p>
      )}
    </Section>
  )
}

function ParamField({ schema, value, onChange, focused, onFocus }) {
  const id = useId()
  if (schema.type === 'boolean') {
    return (
      <div className="v7-param" onMouseDown={onFocus}>
        <label htmlFor={id} className="v7-param-label">{schema.label}</label>
        <Switch id={id} checked={value} onChange={onChange} label={schema.label} />
      </div>
    )
  }
  if (schema.type === 'select') {
    return (
      <div className="v7-param" onMouseDown={onFocus}>
        <span className="v7-param-label">{schema.label}</span>
        <div className="v7-grow"><Select value={value} onChange={onChange} options={schema.options} label={schema.label} /></div>
      </div>
    )
  }
  return (
    <div className={`v7-param v7-param-num${focused ? ' is-focused' : ''}`} onMouseDown={onFocus} onFocus={onFocus}>
      <label htmlFor={id} className="v7-param-label">{schema.label}</label>
      <input
        type="range"
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        className="v7-range"
        aria-label={`${schema.label} slider`}
      />
      <input
        id={id}
        type="number"
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        className="field v7-numfield"
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
      <Fold title="Costs and sizing" summary="per contract, under Account">
        <p className="v7-hint">
          Prop mode sizes in contracts: commission and slippage are set per contract under Account, and capital is the account size.
        </p>
      </Fold>
    )
  }
  const summary = `${costs.slippageBps} bp · $${costs.commissionPerTrade}/fill · $${fmtCompact(costs.initialCapital)} · ${costs.sizePct}×`
  return (
    <Fold title="Costs and sizing" summary={summary}>
      <div className="v7-stack">
        <NumRow label="Slippage (bp per fill)" value={costs.slippageBps} min={0} max={20} step={0.5} onChange={(v) => setCosts({ slippageBps: v })} />
        <p className="v7-hint">Raise this and watch whether the result survives. Most intraday edges don&apos;t.</p>
        <NumRow label="Commission ($ per fill)" value={costs.commissionPerTrade} min={0} max={10} step={0.1} onChange={(v) => setCosts({ commissionPerTrade: v })} />
        <NumRow label="Capital ($)" value={costs.initialCapital} min={1000} max={1000000} step={1000} onChange={(v) => setCosts({ initialCapital: v })} wide />
        <NumRow label="Size (× equity)" value={costs.sizePct} min={0.1} max={3} step={0.1} onChange={(v) => setCosts({ sizePct: v })} />
      </div>
    </Fold>
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
    <Fold title="Exits" summary={summary}>
      <div className="v7-stack">
        <NumRow label="Stop (%)" value={risk.stopPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ stopPct: v })} hint="0 turns it off" />
        <NumRow label="Target (%)" value={risk.targetPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ targetPct: v })} hint="0 turns it off" />
        <NumRow label="Max bars held" value={risk.maxBars} min={0} max={200} step={1} onChange={(v) => setRisk({ maxBars: v })} hint="0 turns it off" />
        <div className="v7-param">
          <span className="v7-param-label">Flat at session close</span>
          {propOn ? (
            <span className="v7-amber v7-small" title="Prop firms require no overnight positions">forced, 16:45 ET</span>
          ) : (
            <Switch checked={risk.flatAtSessionEnd} onChange={(v) => setRisk({ flatAtSessionEnd: v })} label="Flat at session close" />
          )}
        </div>
        <div className="v7-param">
          <span className="v7-param-label">Allow shorts</span>
          <Switch checked={risk.allowShort} onChange={(v) => setRisk({ allowShort: v })} label="Allow shorts" />
        </div>
      </div>
    </Fold>
  )
}

function RunBar() {
  const run = useBacktest((s) => s.run)
  const running = useBacktest((s) => s.running)
  const dataset = useBacktest((s) => s.dataset)
  const result = useBacktest((s) => s.result)
  const autoRun = useBacktest((s) => s.autoRun)
  return (
    <div className="v7-runbar">
      <button type="button" onClick={run} disabled={running || !dataset} className="btn btn-primary v7-runbtn" title="Run backtest (R)">
        {running ? 'Running…' : result ? 'Re-run' : 'Run'} <kbd>R</kbd>
      </button>
      <p className="v7-hint">{autoRun ? 'Auto-run is on: results update as you edit.' : 'Auto-run is off: press Run after changing settings.'}</p>
    </div>
  )
}

const RULE_FIELDS = [
  { key: 'price', label: 'Price ($)' },
  { key: 'activationFee', label: 'Activation ($)' },
  { key: 'profitTarget', label: 'Eval target ($)', evalOnly: true },
  { key: 'evalConsistency', label: 'Eval consistency %', pct: true, evalOnly: true },
  { key: 'maxLoss', label: 'Max loss ($)' },
  { key: 'dailyLossLimit', label: 'Daily limit ($)' },
  { key: 'maxMinis', label: 'Max minis' },
  { key: 'fundedConsistency', label: 'Funded consistency %', pct: true },
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
    <Section title="Account" right={info?.plan?.overridden?.length ? <span className="v7-amber v7-small">rules edited</span> : null}>
      <Choice
        label="Account type"
        value={prop.enabled ? 'prop' : 'cash'}
        onChange={(v) => setProp({ enabled: v === 'prop' })}
        options={[
          { value: 'cash', label: 'Own capital' },
          { value: 'prop', label: 'Prop firm', title: 'Futures only, under a prop firm’s rules' },
        ]}
      />
      {!prop.enabled ? (
        <p className="v7-hint">
          Prop firm mode trades NQ/ES futures in whole contracts under a firm&apos;s evaluation, drawdown and payout rules, and
          prices the account fee against expected payouts.
        </p>
      ) : info.error ? (
        <p className="v7-hint v7-neg">{info.error}</p>
      ) : (
        <div className="v7-stack">
          {FIRM_LIST.length > 1 && (
            <Field label="Firm" row>
              <Select value={prop.firm} onChange={(v) => setProp({ firm: v })} options={FIRM_LIST.map((f) => ({ value: f.id, label: f.label }))} />
            </Field>
          )}
          <div className="v7-seg v7-seg-full" role="radiogroup" aria-label="Plan">
            {plans.map((p) => (
              <button key={p.id} type="button" role="radio" aria-checked={prop.plan === p.id} onClick={() => setProp({ plan: p.id })} title={p.blurb}>
                {p.label.replace(/^Lucid/, '')}
              </button>
            ))}
          </div>
          <p className="v7-hint">{firm.plans[prop.plan]?.blurb}</p>
          <span className="v7-param-label">Account size (price)</span>
          <div className="v7-seg v7-seg-full" role="radiogroup" aria-label="Account size">
            {SIZES.map((sz) => {
              const p = resolvePlan({ ...prop, size: sz.id })
              return (
                <button
                  key={sz.id}
                  type="button"
                  role="radio"
                  aria-checked={prop.size === sz.id}
                  onClick={() => setProp({ size: sz.id })}
                  title={`${p.planLabel} ${sz.label}: max loss $${p.maxLoss.toLocaleString()}, up to ${p.maxMinis} minis / ${p.maxMinis * 10} micros`}
                  className="v7-seg-two"
                >
                  <span>{sz.label}</span>
                  <span className="v7-num v7-dim">${(p.price + p.activationFee).toLocaleString()}</span>
                </button>
              )
            })}
          </div>
          <p className="v7-hint">
            {info.plan.hasEval && <>Target <b className="v7-num">${info.plan.profitTarget.toLocaleString()}</b> · </>}
            Max loss <b className="v7-num">${info.plan.maxLoss.toLocaleString()}</b> · Daily{' '}
            <b className="v7-num">{info.plan.dailyLossLimit ? `$${info.plan.dailyLossLimit.toLocaleString()}` : 'none'}</b> · Up to{' '}
            <b className="v7-num">{info.plan.maxMinis}</b> minis / <b className="v7-num">{info.plan.maxMinis * 10}</b> micros
          </p>
          <div className="v7-param">
            <span className="v7-param-label">Daily loss limit</span>
            <button type="button" aria-pressed={prop.dll} onClick={() => setProp({ dll: !prop.dll })} className={`btn v7-grow ${prop.dll ? 'btn-active' : ''}`}>
              {prop.dll ? (info.plan.dailyLossLimit ? `On · $${info.plan.dailyLossLimit.toLocaleString()}` : 'On · none at this size') : 'Off'}
            </button>
          </div>
          <div className="v7-param">
            <span className="v7-param-label">Account price</span>
            <span className="v7-num">${(info.plan.price + info.plan.activationFee).toLocaleString()}</span>
          </div>
          <Field label="Contract" row>
            <Select value={info.contract.id} onChange={(v) => setProp({ contract: v })} options={contractsForSymbol(symbol).map((c) => ({ value: c.id, label: c.label }))} />
          </Field>
          <NumRow label={`Contracts (max ${info.limit})`} value={info.contracts} min={1} max={info.limit} step={1} onChange={(v) => setProp({ contracts: v })} />
          <NumRow label="Commission ($/side)" value={prop.commissionPerSide} min={0} max={5} step={0.05} onChange={(v) => setProp({ commissionPerSide: v })} hint="Per contract, per side" />
          <NumRow label="Slippage (ticks)" value={prop.slippageTicks} min={0} max={8} step={0.25} onChange={(v) => setProp({ slippageTicks: v })} hint="Ticks per fill (0.25 pt on NQ/ES)" />
          {info.proxy && (
            <div className="v7-param" title="ETF bars are scaled by this ratio to price futures. Seeded from the latest GEX snapshot.">
              <label className="v7-param-label" htmlFor="v7-ratio">{symbol} → {info.contract.family} ratio <span className="v7-amber">(proxy)</span></label>
              <input
                id="v7-ratio"
                type="number"
                step={0.01}
                value={info.priceScale}
                onChange={(e) => setProp({ ratio: { ...prop.ratio, [symbol]: Number(e.target.value) } })}
                className="field v7-numfield v7-numfield-wide"
              />
            </div>
          )}
          <details className="v7-fold v7-fold-inner">
            <summary>
              <span className="v7-fold-title">Firm rules</span>
              <span className="v7-fold-sum">{info.plan.overridden.length ? `${info.plan.overridden.length} edited` : `preset as of ${PROP_ASOF}`}</span>
            </summary>
            <div className="v7-fold-body v7-stack">
              {RULE_FIELDS.filter((f) => !f.evalOnly || info.plan.hasEval).map((f) => {
                const raw = info.plan[f.key]
                const value = f.list ? raw?.[0] : raw
                const shown = value === null || value === undefined ? '' : f.pct ? Number((value * 100).toFixed(2)) : value
                const edited = info.plan.overridden.includes(f.key)
                return (
                  <label key={f.key} className="v7-param">
                    <span className={`v7-param-label ${edited ? 'v7-amber' : ''}`}>{f.label}{edited ? ' (edited)' : ''}</span>
                    <input
                      type="number"
                      value={shown}
                      placeholder="none"
                      onChange={(e) => {
                        const v = e.target.value === '' ? null : Number(e.target.value)
                        setPropOverride(f.key, v === null ? (f.key === 'dailyLossLimit' ? 0 : null) : f.pct ? v / 100 : f.list ? [v] : v)
                      }}
                      className="field v7-numfield v7-numfield-wide"
                    />
                  </label>
                )
              })}
              <div className="v7-line v7-hint">
                <span>
                  Preset as of {PROP_ASOF}. Verify on{' '}
                  <a href={firm.url} target="_blank" rel="noreferrer">{firm.url.replace('https://', '')}</a>
                </span>
                <button type="button" onClick={() => setProp({ overrides: {} })} className="v7-link">Reset rules</button>
              </div>
            </div>
          </details>
        </div>
      )}
    </Section>
  )
}

function NumRow({ label, value, min, max, step, onChange, hint, wide }) {
  const id = useId()
  return (
    <div className="v7-param v7-param-num" title={hint}>
      <label htmlFor={id} className="v7-param-label">{label}</label>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="v7-range" aria-label={`${label} slider`} />
      <input id={id} type="number" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className={`field v7-numfield${wide ? ' v7-numfield-wide' : ''}`} />
    </div>
  )
}

function Field({ label, children, row }) {
  return (
    <label className={row ? 'v7-field v7-field-row' : 'v7-field'}>
      <span className="v7-param-label">{label}</span>
      {children}
    </label>
  )
}

/** Native select (keyboard and screen-reader behaviour for free), restyled. */
function Select({ value, onChange, options, groups, label }) {
  const norm = (list) => list.map((o) => (typeof o === 'string' ? { value: o, label: o } : o))
  const renderOpts = (list) =>
    norm(list).map((o) => (
      <option key={o.value} value={o.value} disabled={o.disabled}>
        {o.label}
      </option>
    ))
  return (
    <div className="v7-select">
      <select value={value} onChange={(e) => onChange(e.target.value)} className="field" aria-label={label}>
        {groups ? groups.map((g) => <optgroup key={g.label} label={g.label}>{renderOpts(g.options)}</optgroup>) : renderOpts(options)}
      </select>
    </div>
  )
}
