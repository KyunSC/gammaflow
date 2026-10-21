'use client'

import { useMemo, useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import { fmtSigned, fmtPctAbs, fmtMoneySigned } from '../../../lib/backtest/format'
import SweepPanel from '../../../components/backtest/SweepPanel'
import WalkForwardPanel from '../../../components/backtest/WalkForwardPanel'
import MonteCarloPanel from '../../../components/backtest/MonteCarloPanel'
import CostPanel from '../../../components/backtest/CostPanel'
import PropPanel from '../../../components/backtest/PropPanel'
import RuleBuilder from '../../../components/backtest/RuleBuilder'
import Trades from './Trades'
import { minus } from './ui'

/**
 * Trades plus the robustness checks, as one tab row. Each check's label says
 * its current state — not run, running, or its headline number — so it is
 * obvious which tests this result has and hasn't been put through.
 */
export default function Checks() {
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const advanced = useBacktest((s) => s.advanced)
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  const result = useBacktest((s) => s.result)
  const sweep = useBacktest((s) => s.sweep)
  const wf = useBacktest((s) => s.wf)
  const mc = useBacktest((s) => s.mc)
  const costCurve = useBacktest((s) => s.costCurve)
  const prop = useBacktest((s) => s.prop)
  const strategyId = useBacktest((s) => s.strategyId)
  const tabRefs = useRef({})

  const breakEven = useMemo(() => {
    if (!costCurve?.length) return undefined
    if (costCurve[0].sharpe <= 0) return null
    for (let i = 1; i < costCurve.length; i++) {
      const a = costCurve[i - 1]
      const b = costCurve[i]
      if (a.sharpe > 0 && b.sharpe <= 0) return a.slippageBps + (a.sharpe / (a.sharpe - b.sharpe)) * (b.slippageBps - a.slippageBps)
    }
    return Infinity
  }, [costCurve])
  const unit = prop.enabled ? 'tk' : 'bp'
  const propStats = result?.prop ? result.prop.bootstrap || result.prop.historical : null

  const tabs = [
    { id: 'blotter', label: 'Trades', status: result ? result.trades.length.toLocaleString() : '—' },
    {
      id: 'sweep',
      label: 'Parameter sweep',
      check: true,
      status: sweep.running ? `${(sweep.progress * 100).toFixed(0)}%` : sweep.data ? `median ${minus(fmtSigned(sweep.data.median))}` : 'not run',
      done: Boolean(sweep.data),
    },
    {
      id: 'wf',
      label: 'Walk-forward',
      check: true,
      status: wf.running ? `fold ${Math.round(wf.progress * 5)}/5` : wf.data ? `OOS ${minus(fmtSigned(wf.data.avgOosSharpe))}` : 'not run',
      done: Boolean(wf.data),
    },
    {
      id: 'mc',
      label: 'Monte Carlo',
      check: true,
      status: mc.running ? 'running' : mc.data ? `P(loss) ${fmtPctAbs(mc.data.probLoss)}` : 'not run',
      done: Boolean(mc.data),
    },
    {
      id: 'costs',
      label: 'Cost ladder',
      check: true,
      status: breakEven === undefined ? 'not run' : breakEven === null ? 'no edge at 0' : breakEven === Infinity ? `> ladder` : `break-even ${breakEven.toFixed(1)} ${unit}`,
      done: breakEven !== undefined,
    },
    { id: 'prop', label: 'Prop account', status: prop.enabled ? (propStats ? `EV ${minus(fmtMoneySigned(propStats.ev))}` : 'on') : 'off' },
    { id: 'rules', label: 'Rule builder', status: strategyId === 'custom' ? 'in use' : 'unused' },
  ]
  const visible = advanced ? tabs : tabs.slice(0, 1)
  const current = visible.some((t) => t.id === activeTab) ? activeTab : 'blotter'
  const checksRun = tabs.filter((t) => t.check && t.done).length

  const onKey = (e) => {
    const i = visible.findIndex((t) => t.id === current)
    let j = null
    if (e.key === 'ArrowRight') j = (i + 1) % visible.length
    else if (e.key === 'ArrowLeft') j = (i - 1 + visible.length) % visible.length
    else if (e.key === 'Home') j = 0
    else if (e.key === 'End') j = visible.length - 1
    if (j === null) return
    e.preventDefault()
    setTab(visible[j].id)
    tabRefs.current[visible[j].id]?.focus()
  }

  return (
    <section className="v7-block v7-checks" aria-label="Trades and robustness checks">
      <div className="v7-tabs-row">
        {!advanced ? (
          <h3 className="v7-checks-h">Trades <span className="v7-num">{tabs[0].status}</span></h3>
        ) : (
        <div className="v7-tabs" role="tablist" aria-label="Trades and checks" onKeyDown={onKey}>
          {visible.map((t) => (
            <button
              key={t.id}
              ref={(el) => { tabRefs.current[t.id] = el }}
              type="button"
              role="tab"
              id={`v7-tab-${t.id}`}
              aria-selected={current === t.id}
              aria-controls="v7-tabpanel"
              tabIndex={current === t.id ? 0 : -1}
              className={`v7-tab${t.done ? ' is-done' : ''}`}
              onClick={() => setTab(t.id)}
            >
              <span className="v7-tab-label">{t.label}</span>
              <span className="v7-tab-status">{t.status}</span>
            </button>
          ))}
        </div>
        )}
        {advanced ? (
          <p className="v7-checks-count" title="Sweep, walk-forward, Monte Carlo and cost ladder for the current settings">
            {checksRun} of 4 checks run for these settings
          </p>
        ) : (
          <p className="v7-checks-count">
            Not yet checked: sweep, walk-forward, Monte Carlo, cost ladder.{' '}
            <button type="button" className="v7-link v7-link-inline" onClick={() => setAdvanced(true)}>
              Show research tools
            </button>
          </p>
        )}
      </div>
      <div className="v7-block-body v7-tabpanel" {...(advanced ? { role: 'tabpanel', id: 'v7-tabpanel', 'aria-labelledby': `v7-tab-${current}` } : {})}>
        {current === 'blotter' && <Trades />}
        {current === 'sweep' && <SweepPanel />}
        {current === 'wf' && <WalkForwardPanel />}
        {current === 'mc' && <MonteCarloPanel />}
        {current === 'costs' && <CostPanel />}
        {current === 'rules' && <RuleBuilder />}
        {current === 'prop' && <PropPanel />}
      </div>
    </section>
  )
}
