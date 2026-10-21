'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { getStrategy, strategiesForPlane, FAMILIES, STRATEGIES } from '../../../lib/backtest/strategies'
import { LIVE_SYMBOLS, LIVE_PERIODS, LIVE_INTERVALS } from '../../../lib/backtest/datasets'
import { propSetup } from '../../../lib/backtest/prop'
import { FIRMS, FIRM_LIST, SIZES, PROP_ASOF, resolvePlan } from '../../../lib/backtest/prop/firms'
import { FUTURES_LIVE_SYMBOLS, contractsForSymbol } from '../../../lib/backtest/prop/contracts'
import { fmtCompact } from '../../../lib/backtest/format'

/**
 * Setup column: data, strategy, costs, exits, account, then Run.
 *
 * Copied from components/backtest/StrategyPanel.jsx with the same store
 * calls. Changes: costs and sizing are always open (they are the most honest
 * control here), the numbered step badges are gone, the focused parameter is
 * marked with an amber rule so it is clear what [ and ] will step, and on
 * narrow screens the whole column folds behind a one-line summary.
 */
export default function Setup({ collapsible = false }) {
  const strategyId = useBacktest((s) => s.strategyId)
  const dataset = useBacktest((s) => s.dataset)
  const costs = useBacktest((s) => s.costs)
  const body = (
    <>
      <DatasetSection />
      <StrategySection />
      <CostSection />
      <RiskSection />
      <PropSection />
    </>
  )
  if (collapsible) {
    return (
      <details className="v4-sec" style={{ padding: '10px 14px', borderBottom: '1px solid var(--v4-rule)' }}>
        <summary>
          <h3>Setup</h3>
          <span className="v4-sum">
            {getStrategy(strategyId).label} · {dataset?.symbol ?? '…'} · {costs.slippageBps} bp
          </span>
        </summary>
        <div>{body}</div>
        <RunBar inline />
      </details>
    )
  }
  return (
    <aside className="v4-setup" aria-label="Setup">
      <div className="v4-setup-body">{body}</div>
      <RunBar />
    </aside>
  )
}

function Section({ title, children, right }) {
  return (
    <section className="v4-sec">
      <div className="v4-sec-h">
        <h3>{title}</h3>
        {right && <span className="v4-sec-right">{right}</span>}
      </div>
      {children}
    </section>
  )
}

/** Starts closed, with its current settings readable in the summary. */
function Collapsible({ title, summary, children }) {
  return (
    <details className="v4-sec">
      <summary>
        <h3>{title}</h3>
        <span className="v4-sum">{summary}</span>
      </summary>
      <div>{children}</div>
    </details>
  )
}

function Segmented({ value, onChange, options }) {
  return (
    <div className="v4-seg2" role="group">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)} aria-pressed={value === o.value} title={o.title}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Switch({ checked, onChange, title, label }) {
  return <button role="switch" aria-checked={Boolean(checked)} aria-label={label} onClick={() => onChange(!checked)} className="switch" title={title} />
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
          { value: 'research', label: 'Historical + GEX', title: 'Published history with bar-aligned gamma levels and model predictions. Needed for Gamma and Model strategies.' },
          { value: 'live', label: 'Live prices', title: 'OHLCV straight from /api/historical, any symbol and interval. No historical GEX: the gamma endpoint only returns the current snapshot.' },
        ]}
      />

      <div className="mt-1.5">
        {plane === 'live' ? (
          <div className="grid grid-cols-3 gap-1">
            <Select value={liveSymbol} onChange={(v) => setLive({ liveSymbol: v })} options={propOn ? FUTURES_LIVE_SYMBOLS : LIVE_SYMBOLS} />
            <Select value={livePeriod} onChange={(v) => setLive({ livePeriod: v })} options={LIVE_PERIODS} />
            <Select value={liveInterval} onChange={(v) => setLive({ liveInterval: v })} options={LIVE_INTERVALS} />
          </div>
        ) : (
          <Select
            value={researchSymbol}
            onChange={setResearchSymbol}
            options={researchSets.length ? researchSets.map((d) => d.symbol) : ['QQQ', 'SPY']}
          />
        )}
      </div>

      <p className="v4-note mt-1.5">
        {loading
          ? 'Loading…'
          : plane === 'research'
            ? `5-minute bars with bar-aligned gamma levels${example ? ', from the bundled sample file' : ''}.`
            : 'Recent prices only — Gamma and Model strategies need historical data.'}
      </p>

      {advanced && (
        <div className="mt-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            {plane === 'research' && (
              <label className="flex flex-1 items-center gap-2 text-[12px] text-muted">
                <input type="checkbox" checked={example} onChange={(e) => setExample(e.target.checked)} />
                Bundled sample
              </label>
            )}
            <button className="btn" disabled={loading} onClick={refreshDataset}>
              {loading ? 'Loading…' : 'Refresh'}
            </button>
          </div>
          {dataset && (
            <p className="v4-note">
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
        <button onClick={resetParams} className="hover:text-ink" title="Reset parameters to defaults">
          Reset to defaults
        </button>
      }
    >
      <Select value={strategyId} onChange={setStrategy} groups={groups} />
      <p className="v4-note mt-1.5 mb-2">{strategy.blurb}</p>

      <div className="flex flex-col gap-0.5">
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
            Open rule builder
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
    <span className="v4-row-label" title={focused ? `${schema.label}: [ and ] step this` : schema.label}>
      {schema.label}
    </span>
  )

  if (schema.type === 'boolean') {
    return (
      <div className="v4-row" onMouseDown={onFocus}>
        {label}
        <span className="flex-1" />
        <Switch checked={value} onChange={onChange} label={schema.label} />
      </div>
    )
  }

  if (schema.type === 'select') {
    return (
      <div className="v4-row" onMouseDown={onFocus}>
        {label}
        <div className="flex-1">
          <Select value={value} onChange={onChange} options={schema.options} label={schema.label} />
        </div>
      </div>
    )
  }

  return (
    <div className={`v4-row ${focused ? 'v4-focused' : ''}`} onMouseDown={onFocus} onFocus={onFocus}>
      {label}
      <input
        type="range"
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={schema.label}
        className="h-[3px] min-w-0 flex-1 cursor-pointer appearance-none rounded bg-hair-bright"
      />
      <input
        type="number"
        min={schema.min}
        max={schema.max}
        step={schema.step}
        value={value ?? schema.default}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`${schema.label} value`}
        className="field !w-[62px] shrink-0 !px-1 !py-0.5 text-right"
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
      <Collapsible title="Costs and sizing" summary="per contract">
        <p className="v4-note">
          Prop mode sizes in contracts: commission and slippage are set per contract under{' '}
          <span className="text-muted">account</span>, and capital is the account size.
        </p>
      </Collapsible>
    )
  }

  return (
    <Section title="Costs and sizing" right={`$${fmtCompact(costs.initialCapital)} · ${costs.sizePct}× equity`}>
      <div className="flex flex-col gap-0.5">
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
      <p className="v4-note mt-1">Slippage is charged on every fill and commission on both sides of each trade.</p>
    </Section>
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
      <div className="flex flex-col gap-0.5">
        <NumRow label="Stop (%)" value={risk.stopPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ stopPct: v })} hint="0 disables" />
        <NumRow label="Target (%)" value={risk.targetPct} min={0} max={10} step={0.05} onChange={(v) => setRisk({ targetPct: v })} hint="0 disables" />
        <NumRow label="Max bars" value={risk.maxBars} min={0} max={200} step={1} onChange={(v) => setRisk({ maxBars: v })} hint="0 disables" />
        <div className="v4-row">
          <span className="v4-row-label">Flat at close</span>
          <span className="flex-1" />
          {propOn ? (
            <span className="text-[11px] text-amber" title="Prop firms require no overnight positions">
              Forced, 16:45 ET
            </span>
          ) : (
            <Switch checked={risk.flatAtSessionEnd} onChange={(v) => setRisk({ flatAtSessionEnd: v })} label="Flat at close" />
          )}
        </div>
        <div className="v4-row">
          <span className="v4-row-label">Allow shorts</span>
          <span className="flex-1" />
          <Switch checked={risk.allowShort} onChange={(v) => setRisk({ allowShort: v })} label="Allow shorts" />
        </div>
      </div>
    </Collapsible>
  )
}

/** Footer so Run never scrolls out of reach. */
function RunBar({ inline = false }) {
  const run = useBacktest((s) => s.run)
  const running = useBacktest((s) => s.running)
  const dataset = useBacktest((s) => s.dataset)
  const autoRun = useBacktest((s) => s.autoRun)
  const toggleAutoRun = useBacktest((s) => s.toggleAutoRun)

  return (
    <div className="v4-runbar" style={inline ? { padding: '10px 0 2px', borderTop: 'none' } : undefined}>
      <button onClick={run} disabled={running || !dataset} className="v4-run" title="Run backtest (R)">
        {running ? 'Running…' : autoRun ? 'Run again' : 'Run backtest'}
        <span className="v4-kbd">R</span>
      </button>
      <label className="mt-2 flex cursor-pointer items-center gap-2 text-[12px] text-dim">
        <Switch checked={autoRun} onChange={toggleAutoRun} title="Re-run automatically when a setting changes" label="Auto-run" />
        <span>{autoRun ? 'Re-runs when a setting changes' : 'Auto-run off: press Run or R'}</span>
      </label>
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
    <Section title="Account" right={info?.plan?.overridden?.length ? <span className="text-amber">rules edited</span> : null}>
      <div className="mb-1.5">
        <Segmented
          value={prop.enabled ? 'prop' : 'cash'}
          onChange={(v) => setProp({ enabled: v === 'prop' })}
          options={[
            { value: 'cash', label: 'Own capital' },
            { value: 'prop', label: 'Prop firm', title: "Futures only, under a prop firm's rules" },
          ]}
        />
      </div>

      {!prop.enabled ? (
        <p className="v4-note">Prop firm: whole NQ/ES contracts under an evaluation, drawdown and payout rule set, priced per account.</p>
      ) : info.error ? (
        <p className="text-[10px] leading-snug text-neg">{info.error}</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {FIRM_LIST.length > 1 && (
            <Select value={prop.firm} onChange={(v) => setProp({ firm: v })} options={FIRM_LIST.map((f) => ({ value: f.id, label: f.label }))} />
          )}
          <div className="grid grid-cols-4 gap-1">
            {plans.map((p) => (
              <button key={p.id} onClick={() => setProp({ plan: p.id })} className={`btn !px-1 text-[10px] ${prop.plan === p.id ? 'btn-active' : ''}`} title={p.blurb}>
                {p.label.replace(/^Lucid/, '')}
              </button>
            ))}
          </div>
          <p className="v4-note">{firm.plans[prop.plan]?.blurb}</p>
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
          <p className="v4-note">
            {info.plan.hasEval && <>Target <span className="num text-muted">${info.plan.profitTarget.toLocaleString()}</span> · </>}
            Max loss <span className="num text-muted">${info.plan.maxLoss.toLocaleString()}</span> ·
            Daily <span className="num text-muted">{info.plan.dailyLossLimit ? `$${info.plan.dailyLossLimit.toLocaleString()}` : 'none'}</span> ·
            Up to <span className="num text-muted">{info.plan.maxMinis}</span> minis / <span className="num text-muted">{info.plan.maxMinis * 10}</span> micros
          </p>
          <div className="flex items-center gap-2">
            <span className="v4-row-label">Daily limit</span>
            <button onClick={() => setProp({ dll: !prop.dll })} className={`btn flex-1 !py-1 ${prop.dll ? 'btn-active' : ''}`}>
              {prop.dll ? (info.plan.dailyLossLimit ? `on · $${info.plan.dailyLossLimit.toLocaleString()}` : 'on · none at this size') : 'off'}
            </button>
          </div>
          <div className="flex items-baseline justify-between font-mono text-[11px]">
            <span className="text-muted">Account price</span>
            <span className="num text-ink">${(info.plan.price + info.plan.activationFee).toLocaleString()}</span>
          </div>

          <div className="flex items-center gap-2">
            <span className="v4-row-label">Contract</span>
            <div className="flex-1">
              <Select
                value={info.contract.id}
                onChange={(v) => setProp({ contract: v })}
                options={contractsForSymbol(symbol).map((c) => ({ value: c.id, label: c.label }))}
              />
            </div>
          </div>
          <NumRow label={`Qty (max ${info.limit})`} value={info.contracts} min={1} max={info.limit} step={1} onChange={(v) => setProp({ contracts: v })} />
          <NumRow label="Comm. $/side" value={prop.commissionPerSide} min={0} max={5} step={0.05} onChange={(v) => setProp({ commissionPerSide: v })} hint="Per contract, per side" />
          <NumRow label="Slippage (tk)" value={prop.slippageTicks} min={0} max={8} step={0.25} onChange={(v) => setProp({ slippageTicks: v })} hint="Ticks per fill (0.25 pt on NQ/ES)" />
          {info.proxy && (
            <div className="flex items-center gap-2" title="ETF bars are scaled by this ratio to price futures. Seeded from the latest GEX snapshot.">
              <span className="v4-row-label">
                {symbol}→{info.contract.family}
              </span>
              <input
                type="number"
                step={0.01}
                value={info.priceScale}
                onChange={(e) => setProp({ ratio: { ...prop.ratio, [symbol]: Number(e.target.value) } })}
                className="field flex-1 !px-1 !py-0.5 text-right"
              />
              <span className="rounded-[2px] border border-amber-dim px-1 text-[9px] text-amber">proxy</span>
            </div>
          )}

          <details className="mt-0.5">
            <summary className="cursor-pointer text-[12px] text-muted hover:text-ink">
              Rules{info.plan.overridden.length > 0 && ` · ${info.plan.overridden.length} edited`}
            </summary>
            <div className="mt-1.5 flex flex-col gap-1">
              {RULE_FIELDS.filter((f) => !f.evalOnly || info.plan.hasEval).map((f) => {
                const raw = info.plan[f.key]
                const value = f.list ? raw?.[0] : raw
                const shown = value === null || value === undefined ? '' : f.pct ? Number((value * 100).toFixed(2)) : value
                const edited = info.plan.overridden.includes(f.key)
                return (
                  <label key={f.key} className="flex items-center gap-2">
                    <span className="v4-row-label" style={edited ? { color: 'var(--v4-amber)' } : undefined}>{f.label}</span>
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
              <div className="flex items-center justify-between text-[10px] text-dim">
                <span>
                  Preset as of {PROP_ASOF}. Verify on{' '}
                  <a href={firm.url} target="_blank" rel="noreferrer" className="text-muted underline">
                    {firm.url.replace('https://', '')}
                  </a>
                </span>
                <button onClick={() => setProp({ overrides: {} })} className="hover:text-ink">
                  Reset rules
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
    <div className="v4-row" title={hint}>
      <span className="v4-row-label">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
        className="h-[3px] min-w-0 flex-1 cursor-pointer appearance-none rounded bg-hair-bright"
      />
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`${label} value`}
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
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} className="field cursor-pointer pr-5 !text-[12px]">
        {groups
          ? groups.map((g) => (
              <optgroup key={g.label} label={g.label} className="bg-panel text-dim">
                {renderOpts(g.options)}
              </optgroup>
            ))
          : renderOpts(options)}
      </select>
      <span className="pointer-events-none absolute top-1/2 right-1.5 -translate-y-1/2 text-[8px] text-dim" aria-hidden="true">▼</span>
    </div>
  )
}
