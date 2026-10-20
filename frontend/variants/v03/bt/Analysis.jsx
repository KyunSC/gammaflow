'use client'

import { useRef } from 'react'
import { useBacktest } from '../../../lib/backtest/store'
import SweepPanel from '../../../components/backtest/SweepPanel'
import WalkForwardPanel from '../../../components/backtest/WalkForwardPanel'
import MonteCarloPanel from '../../../components/backtest/MonteCarloPanel'
import CostPanel from '../../../components/backtest/CostPanel'
import RuleBuilder from '../../../components/backtest/RuleBuilder'
import PropPanel from '../../../components/backtest/PropPanel'
import Trades from './Trades'

// Labels say what each tab answers; the key is the shortcut that runs it.
export const TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep', key: 'S' },
  { id: 'wf', label: 'Walk-forward', key: 'W' },
  { id: 'mc', label: 'Monte Carlo', key: 'M' },
  { id: 'costs', label: 'Cost ladder' },
  { id: 'prop', label: 'Prop account' },
  { id: 'rules', label: 'Rules' },
]

/** Advanced view's lower region: the trade list and the research tools as
 *  real tabs (arrow keys move between them). Tab bodies are the shared panels. */
export default function Analysis() {
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const listRef = useRef(null)

  const onKeyDown = (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const i = TABS.findIndex((t) => t.id === activeTab)
    const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length]
    setTab(next.id)
    listRef.current?.querySelector(`[data-tab="${next.id}"]`)?.focus()
  }

  return (
    <section className="v3-region v3-fill" aria-label="Analysis">
      <div className="v3-tabs" role="tablist" aria-label="Analysis tools" ref={listRef} onKeyDown={onKeyDown}>
        {TABS.map((t) => (
          <button
            type="button"
            key={t.id}
            role="tab"
            data-tab={t.id}
            id={`v3-tab-${t.id}`}
            aria-selected={activeTab === t.id}
            aria-controls="v3-tabpanel"
            tabIndex={activeTab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            className={`v3-tab ${activeTab === t.id ? 'is-on' : ''}`}
          >
            {t.label}
            {t.key && <kbd className="v3-tab-key">{t.key}</kbd>}
          </button>
        ))}
      </div>
      <div className="v3-region-body v3-tabbody" role="tabpanel" id="v3-tabpanel" aria-labelledby={`v3-tab-${activeTab}`}>
        {activeTab === 'blotter' && <Trades />}
        {activeTab === 'sweep' && <SweepPanel />}
        {activeTab === 'wf' && <WalkForwardPanel />}
        {activeTab === 'mc' && <MonteCarloPanel />}
        {activeTab === 'costs' && <CostPanel />}
        {activeTab === 'rules' && <RuleBuilder />}
        {activeTab === 'prop' && <PropPanel />}
      </div>
    </section>
  )
}
