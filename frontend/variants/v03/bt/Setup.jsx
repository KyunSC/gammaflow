'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy, strategiesForPlane, FAMILIES, STRATEGIES } from '../../../lib/backtest/strategies'
import { LIVE_SYMBOLS, LIVE_PERIODS, LIVE_INTERVALS } from '../../../lib/backtest/datasets'
import { propSetup } from '../../../lib/backtest/prop'
import { FIRMS, FIRM_LIST, SIZES, PROP_ASOF, resolvePlan } from '../../../lib/backtest/prop/firms'
import { FUTURES_LIVE_SYMBOLS, contractsForSymbol } from '../../../lib/backtest/prop/contracts'
import { fmtCompact } from '../../../lib/backtest/format'
import { Select, Switch, NumRow, Segmented } from './ui'
import DataQuality from './DataQuality'

/**
 * Setup column: data, strategy, costs, exits, account, then Run.
 * Same controls and store actions as components/backtest/StrategyPanel; the
 * changes are presentation and labelling (every input has a name, costs are
 * open by default because the headline numbers depend on them).
 */
export default function Setup() {
  return (
    <div className="v3-setup" id="v3-setup">
      <div className="v3-setup-scroll v3-scroll">
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

function Group({ title, aside, children }) {
  return (
    <fieldset className="v3-group">
      <legend className="v3-group-title">
        <span>{title}</span>
        {aside}
      </legend>
      {children}
    </fieldset>
  )
}

function Fold({ title, summary, children, open }) {
  return (
    <details className="v3-fold" open={open}>
      <summary>
        <span className="v3-fold-title">{title}</span>
        <span className="v3-fold-summary">{summary}</span>
      </summary>
      <div className="v3-fold-body">{children}</div>
    </details>
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
  const example = useBacktest((s) => s.example)
  const setExample = useBacktest((s) => s.setExample)
  const refreshDataset = useBacktest((s) => s.refreshDataset)
  const loading = useBacktest((s) => s.datasetLoading)
  const propOn = useBacktest((s) => s.prop.enabled)
  const researchSets = researchIndex?.datasets || []

  return (
    <Group title="Data">
      <Segmented
        label="Data source"
        value={plane}
        onChange={setPlane}
        options={[
          { value: 'research', label: 'Historical + GEX', title: 'Published history with bar-aligned gamma levels and model predictions. Needed for Gamma and Model strategies.' },
          { value: 'live', label: 'Live prices', title: 'OHLCV straight from /api/historical, any symbol and interval. No historical GEX: the gamma endpoint only returns the current snapshot.' },
        ]}
      />
      {plane === 'live' ? (
        <div className="v3-row3">
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
      <p className="v3-note">
        {loading
          ? 'Loading…'
          : plane === 'research'
            ? example
              ? '5-minute bars with gamma levels, from the bundled sample file.'
              : '5-minute bars with gamma levels.'
            : 'Recent prices only. Gamma and Model strategies need historical data.'}
      </p>
      <DataQuality />

      {advanced && (
        <div className="v3-stack-sm">
          <div className="v3-inline">
            {plane === 'research' && (
              <label className="v3-check">
                <input type="checkbox" checked={example} onChange={(e) => setExample(e.target.checked)} />
                Use bundled sample
              </label>
            )}
            <button type="button" className="btn v3-btn-sm" disabled={loading} onClick={refreshDataset}>
              {loading ? 'Loading…' : 'Reload data'}
            </button>
          </div>
          {dataset && (
            <p className="v3-note">
              {dataset.generatedAt && <>Generated {dataset.generatedAt.slice(0, 10)}. </>}
              {dataset.version && <>Version {dataset.version.slice(0, 8)}. </>}
              {(dataset.cached || researchIndex?.cached) && <>Offline cache, up to 24h old. </>}
              {dataset.quality?.predictionValidation === 'legacy-unverified' && <>Legacy model predictions; training overlap unverified. </>}
              {dataset.plane === 'live' && <>Exploratory snapshot; shared links reload current history. </>}
              {dataset.plane === 'research' && dataset.ml && <>Model: {dataset.ml.model}, {dataset.ml.horizon}.</>}
            </p>
          )}
        </div>
      )}
    </Group>
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
    label: `${f.label}  (Alt+${f.hotkey})`,
    options: STRATEGIES.filter((s) => s.family === f.id).map((s) => ({
      value: s.id,
      label: available.has(s.id) ? s.label : `${s.label} (${s.plane === 'research' && plane !== 'research' ? 'needs historical data' : 'not in this dataset'})`,
      disabled: !available.has(s.id),
    })),
  })).filter((g) => g.options.length)

  const schema = strategy.params.filter((p) => !p.hidden)

  return (
    <Group
      title="Strategy"
      aside={
        <button type="button" onClick={resetParams} className="v3-link" title="Reset parameters to defaults">
          Reset
        </button>
      }
    >
      <Select label="Strategy" value={strategyId} onChange={setStrategy} groups={groups} />
      <p className="v3-note">{strategy.blurb}</p>
      <div className="v3-stack-sm">
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
        {schema.some((p) => p.type === 'number') && (
          <p className="v3-note v3-note-quiet">
            Click a parameter, then <kbd className="kbd">[</kbd> <kbd className="kbd">]</kbd> steps it.
          </p>
        )}
        {strategyId === 'custom' && (
          <button
            type="button"
            onClick={() => {
              setAdvanced(true)
              setTab('rules')
            }}
            className="btn"
          >
            Open rule builder
          </button>
        )}
      </div>
    </Group>
  )
}

function ParamField({ schema, value, onChange, focused, onFocus }) {
  if (schema.type === 'boolean') {
    return (
      <div className="v3-num" onMouseDown={onFocus}>
        <span className="v3-num-label">{schema.label}</span>
        <span className="v3-grow" />
        <Switch checked={value} onChange={onChange} label={schema.label} />
      </div>
    )
  }
  if (schema.type === 'select') {
    return (
      <div className="v3-num" onMouseDown={onFocus}>
        <span className="v3-num-label">{schema.label}</span>
        <div className="v3-grow">
          <Select label={schema.label} value={value} onChange={onChange} options={schema.options} />
        </div>
      </div>
    )
  }
  return (
    <NumRow
      label={schema.label}
      value={value ?? schema.default}
      min={schema.min}
      max={schema.max}
      step={schema.step}
      onChange={onChange}
      focused={focused}
      onFocus={onFocus}
    />
  )
}

function CostSection() {
  const costs = useBacktest((s) => s.costs)
  const setCosts = useBacktest((s) => s.setCosts)
  const propOn = useBacktest((s) => s.prop.enabled)

  if (propOn) {
    return (
      <Fold title="Costs and sizing" summary="per contract, under Account">
        <p className="v3-note">
          Prop mode sizes in contracts: commission and slippage are set per contract under Account, and capital is the account size.
        </p>
      </Fold>
    )
  }

  const summary = `${costs.slippageBps} bp · $${costs.commissionPerTrade}/trade · $${fmtCompact(costs.initialCapital)} · ${costs.sizePct}×`
  return (
    <Fold title="Costs and sizing" summary={summary} open>
      <div className="v3-stack-sm">
        <NumRow label="Slippage (bp)" value={costs.slippageBps} min={0} max={20} step={0.5} onChange={(v) => setCosts({ slippageBps: v })} hint="Per fill. Raise it until the edge is gone; that number is worth knowing." />
        <NumRow label="Commission ($)" value={costs.commissionPerTrade} min={0} max={10} step={0.1} onChange={(v) => setCosts({ commissionPerTrade: v })} />
        <NumRow label="Capital ($)" value={costs.initialCapital} min={1000} max={1000000} step={1000} onChange={(v) => setCosts({ initialCapital: v })} />
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
      <div className="v3-stack-sm">
        <NumRow label="Stop (%)" value={risk.stopPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ stopPct: v })} hint="0 disables" />
        <NumRow label="Target (%)" value={risk.targetPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ targetPct: v })} hint="0 disables" />
        <NumRow label="Max bars" value={risk.maxBars} min={0} max={200} step={1} onChange={(v) => setRisk({ maxBars: v })} hint="0 disables" />
        <div className="v3-num">
          <span className="v3-num-label">Flat at close</span>
          <span className="v3-grow" />
          {propOn ? (
            <span className="v3-tag" title="Prop firms require no overnight positions">forced, 16:45 ET</span>
          ) : (
            <Switch label="Flat at close" checked={risk.flatAtSessionEnd} onChange={(v) => setRisk({ flatAtSessionEnd: v })} />
          )}
        </div>
        <div className="v3-num">
          <span className="v3-num-label">Allow shorts</span>
          <span className="v3-grow" />
          <Switch label="Allow shorts" checked={risk.allowShort} onChange={(v) => setRisk({ allowShort: v })} />
        </div>
      </div>
    </Fold>
  )
}

function RunBar() {
  const run = useBacktest((s) => s.run)
  const running = useBacktest((s) => s.running)
  const dataset = useBacktest((s) => s.dataset)
  const autoRun = useBacktest((s) => s.autoRun)
  const toggleAutoRun = useBacktest((s) => s.toggleAutoRun)

  return (
    <div className="v3-runbar">
      <button type="button" onClick={run} disabled={running || !dataset} className="btn btn-primary v3-run" title="Run backtest (R)">
        {running ? 'Running…' : autoRun ? 'Re-run' : 'Run'} <kbd className="v3-run-key">R</kbd>
      </button>
      <label className="v3-check v3-autorun">
        <Switch checked={autoRun} onChange={toggleAutoRun} label="Re-run when a setting changes" />
        <span>{autoRun ? 'Re-runs when a setting changes' : 'Runs only when you press Run'}</span>
      </label>
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
    <Group title="Account" aside={info?.plan?.overridden?.length ? <span className="v3-tag">rules edited</span> : null}>
      <Segmented
        label="Account type"
        value={prop.enabled ? 'prop' : 'cash'}
        onChange={(v) => setProp({ enabled: v === 'prop' })}
        options={[
          { value: 'cash', label: 'Cash' },
          { value: 'prop', label: 'Prop firm', title: 'Futures only, under a prop firm’s rules' },
        ]}
      />
      {!prop.enabled ? (
        <p className="v3-note">
          Prop mode trades NQ/ES futures in whole contracts under a firm&apos;s evaluation, drawdown and payout rules, and prices the account. Some strategies only pay when the fee caps the downside.
        </p>
      ) : info.error ? (
        <p className="v3-note v3-note-error" role="alert">{info.error}</p>
      ) : (
        <div className="v3-stack-sm">
          {FIRM_LIST.length > 1 && (
            <Select label="Firm" value={prop.firm} onChange={(v) => setProp({ firm: v })} options={FIRM_LIST.map((f) => ({ value: f.id, label: f.label }))} />
          )}
          <Segmented
            label="Plan"
            value={prop.plan}
            onChange={(v) => setProp({ plan: v })}
            options={plans.map((p) => ({ value: p.id, label: p.label.replace(/^Lucid/, ''), title: p.blurb }))}
          />
          <p className="v3-note">{firm.plans[prop.plan]?.blurb}</p>
          <div className="v3-seg v3-seg-4" role="radiogroup" aria-label="Account size">
            {SIZES.map((sz) => {
              const p = resolvePlan({ ...prop, size: sz.id })
              return (
                <button
                  type="button"
                  role="radio"
                  aria-checked={prop.size === sz.id}
                  key={sz.id}
                  onClick={() => setProp({ size: sz.id })}
                  className={`v3-seg-btn v3-seg-tall ${prop.size === sz.id ? 'is-on' : ''}`}
                  title={`${p.planLabel} ${sz.label}: max loss $${p.maxLoss.toLocaleString()}, up to ${p.maxMinis} minis / ${p.maxMinis * 10} micros`}
                >
                  <span>{sz.label}</span>
                  <span className="v3-num-sub">${(p.price + p.activationFee).toLocaleString()}</span>
                </button>
              )
            })}
          </div>
          <dl className="v3-facts">
            {info.plan.hasEval && <><dt>Eval target</dt><dd>${info.plan.profitTarget.toLocaleString()}</dd></>}
            <dt>Max loss</dt><dd>${info.plan.maxLoss.toLocaleString()}</dd>
            <dt>Daily limit</dt><dd>{info.plan.dailyLossLimit ? `$${info.plan.dailyLossLimit.toLocaleString()}` : 'none'}</dd>
            <dt>Size cap</dt><dd>{info.plan.maxMinis} minis / {info.plan.maxMinis * 10} micros</dd>
            <dt>Account price</dt><dd>${(info.plan.price + info.plan.activationFee).toLocaleString()}</dd>
          </dl>
          <div className="v3-num">
            <span className="v3-num-label">Daily limit</span>
            <span className="v3-grow" />
            <Switch label="Apply daily loss limit" checked={prop.dll} onChange={(v) => setProp({ dll: v })} />
            <span className="v3-num-sub">{prop.dll ? (info.plan.dailyLossLimit ? `$${info.plan.dailyLossLimit.toLocaleString()}` : 'none at this size') : 'off'}</span>
          </div>
          <div className="v3-num">
            <span className="v3-num-label">Contract</span>
            <div className="v3-grow">
              <Select label="Contract" value={info.contract.id} onChange={(v) => setProp({ contract: v })} options={contractsForSymbol(symbol).map((c) => ({ value: c.id, label: c.label }))} />
            </div>
          </div>
          <NumRow label={`Qty (max ${info.limit})`} value={info.contracts} min={1} max={info.limit} step={1} onChange={(v) => setProp({ contracts: v })} />
          <NumRow label="Comm. $/side" value={prop.commissionPerSide} min={0} max={5} step={0.05} onChange={(v) => setProp({ commissionPerSide: v })} hint="Per contract, per side" />
          <NumRow label="Slippage (ticks)" value={prop.slippageTicks} min={0} max={8} step={0.25} onChange={(v) => setProp({ slippageTicks: v })} hint="Ticks per fill (0.25 pt on NQ/ES)" />
          {info.proxy && (
            <label className="v3-num" title="ETF bars are scaled by this ratio to price futures. Seeded from the latest GEX snapshot.">
              <span className="v3-num-label">{symbol}→{info.contract.family} ratio</span>
              <input
                type="number"
                step={0.01}
                value={info.priceScale}
                onChange={(e) => setProp({ ratio: { ...prop.ratio, [symbol]: Number(e.target.value) } })}
                className="field v3-grow v3-num-input"
              />
              <span className="v3-tag">proxy</span>
            </label>
          )}
          <details className="v3-fold">
            <summary>
              <span className="v3-fold-title">Firm rules</span>
              <span className="v3-fold-summary">{info.plan.overridden.length > 0 ? `${info.plan.overridden.length} edited` : `preset as of ${PROP_ASOF}`}</span>
            </summary>
            <div className="v3-fold-body v3-stack-sm">
              {RULE_FIELDS.filter((f) => !f.evalOnly || info.plan.hasEval).map((f) => {
                const raw = info.plan[f.key]
                const value = f.list ? raw?.[0] : raw
                const shown = value === null || value === undefined ? '' : f.pct ? Number((value * 100).toFixed(2)) : value
                const edited = info.plan.overridden.includes(f.key)
                return (
                  <label key={f.key} className="v3-num">
                    <span className={`v3-num-label ${edited ? 'v3-amber' : ''}`}>{f.label}</span>
                    <input
                      type="number"
                      value={shown}
                      placeholder="none"
                      onChange={(e) => {
                        const v = e.target.value === '' ? null : Number(e.target.value)
                        setPropOverride(f.key, v === null ? (f.key === 'dailyLossLimit' ? 0 : null) : f.pct ? v / 100 : f.list ? [v] : v)
                      }}
                      className="field v3-grow v3-num-input"
                    />
                  </label>
                )
              })}
              <p className="v3-note">
                Preset as of {PROP_ASOF}. Check it against{' '}
                <a href={firm.url} target="_blank" rel="noreferrer" className="v3-a">
                  {firm.url.replace('https://', '')}
                </a>{' '}
                before relying on it.{' '}
                <button type="button" onClick={() => setProp({ overrides: {} })} className="v3-link">
                  Reset rules
                </button>
              </p>
            </div>
          </details>
        </div>
      )}
    </Group>
  )
}
