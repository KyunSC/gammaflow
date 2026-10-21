'use client'

import { useEffect, useRef } from 'react'
import { MotionConfig } from 'framer-motion'
import { Group as PanelGroup, Panel as RPanel, Separator as PanelResizeHandle } from 'react-resizable-panels'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, FAMILIES, strategiesForPlane } from '../../lib/backtest/strategies'
import { decodeConfig } from '../../lib/backtest/share'
import ComparePanel from '../../components/backtest/ComparePanel'
import SweepPanel from '../../components/backtest/SweepPanel'
import WalkForwardPanel from '../../components/backtest/WalkForwardPanel'
import MonteCarloPanel from '../../components/backtest/MonteCarloPanel'
import CostPanel from '../../components/backtest/CostPanel'
import RuleBuilder from '../../components/backtest/RuleBuilder'
import PropPanel from '../../components/backtest/PropPanel'
import CommandPalette from '../../components/backtest/CommandPalette'
import Header from './bt/Header'
import Verdict from './bt/Verdict'
import Caveats from './bt/Caveats'
import PriceChart from './bt/PriceChart'
import EquityChart from './bt/EquityChart'
import Trades from './bt/Trades'
import Setup from './bt/Setup'
import Metrics from './bt/Metrics'
import Shortcuts from './bt/Shortcuts'
import Section from './bt/Section'
import { useMedia } from './bt/ui'
import { fontVars } from './fonts'
import './v06.css'

const TABS = [
  { id: 'blotter', label: 'Trades' },
  { id: 'sweep', label: 'Sweep' },
  { id: 'wf', label: 'Walk-forward' },
  { id: 'mc', label: 'Monte Carlo' },
  { id: 'costs', label: 'Cost ladder' },
  { id: 'prop', label: 'Prop account' },
  { id: 'rules', label: 'Rules' },
]

/**
 * UI 06, "Session Ledger". Same store, same engine, same shortcuts as the
 * original terminal. Layout: setup on the left; price, equity and the trade
 * list (or the research tabs) in the middle; the verdict, its caveats and the
 * full metrics on the right, so nothing that qualifies a number is further
 * than one glance from it.
 */
export default function Backtest() {
  const advanced = useBacktest((s) => s.advanced)
  const wide = useMedia('(min-width: 1024px)')

  useEffect(() => {
    const store = useBacktest.getState()
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  useKeyboard()

  return (
    <MotionConfig reducedMotion="user">
      <div className="v6-bt" style={fontVars}>
        <Header wide={wide} />
        <Notices />
        {wide ? <Wide advanced={advanced} /> : <Stacked advanced={advanced} />}
        <CommandPalette />
        <Shortcuts />
      </div>
    </MotionConfig>
  )
}

function Notices() {
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const setExample = useBacktest((s) => s.setExample)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const loadDataset = useBacktest((s) => s.loadDataset)
  if (!datasetNotice && !datasetError && !runError && !configError) return null
  return (
    <div className="v6-notices" role="status">
      {datasetNotice && !datasetError && (
        <p className="v6-notice" data-tone="warn">
          <span>{datasetNotice}</span>
          <button type="button" onClick={() => setExample(false)} className="btn">Try the server again</button>
        </p>
      )}
      {datasetError && (
        <p className="v6-notice" data-tone="bad">
          <span>{datasetError}</span>
          <button type="button" onClick={loadDataset} className="btn">Retry</button>
        </p>
      )}
      {runError && <p className="v6-notice" data-tone="bad"><span>Run failed: {runError}</span></p>}
      {configError && <p className="v6-notice" data-tone="warn"><span>{configError}</span></p>}
    </div>
  )
}

const Sep = ({ dir }) => <PanelResizeHandle className={`v6-sep v6-sep-${dir}`} />

function Wide({ advanced }) {
  return (
    <PanelGroup orientation="horizontal" className="v6-cols min-h-0 flex-1">
      <RPanel defaultSize="21" minSize="16" maxSize="32" className="min-h-0">
        <div className="h-full overflow-hidden"><Setup /></div>
      </RPanel>
      <Sep dir="v" />
      <RPanel defaultSize="55" minSize="34" className="min-h-0">
        <PanelGroup orientation="vertical">
          <RPanel defaultSize="44" minSize="18"><PriceChart /></RPanel>
          <Sep dir="h" />
          <RPanel defaultSize="24" minSize="12"><EquityChart /></RPanel>
          <Sep dir="h" />
          <RPanel defaultSize="32" minSize="14"><Lower advanced={advanced} /></RPanel>
        </PanelGroup>
      </RPanel>
      <Sep dir="v" />
      <RPanel defaultSize="24" minSize="18" maxSize="36" className="min-h-0">
        <Reading advanced={advanced} />
      </RPanel>
    </PanelGroup>
  )
}

/** Under 1024px: the answer first, then the evidence, then the controls. */
function Stacked({ advanced }) {
  return (
    <div className="v6-stack">
      <Verdict />
      <Section title="Before you trust it" scroll={false}><Caveats /></Section>
      <div className="h-[320px] shrink-0"><PriceChart /></div>
      <div className="h-[240px] shrink-0"><EquityChart /></div>
      <div className={`${advanced ? 'h-[460px]' : 'h-[380px]'} shrink-0`}><Lower advanced={advanced} /></div>
      <Setup id="v6-setup" />
      {advanced && <Metrics />}
      {advanced && <div className="v6-compare"><ComparePanel /></div>}
      {!advanced && <AdvancedNote />}
    </div>
  )
}

function Reading({ advanced }) {
  return (
    <div className="v6-reading h-full overflow-auto">
      <Verdict />
      <Section title="Before you trust it" scroll={false}><Caveats /></Section>
      {advanced ? (
        <>
          <Metrics />
          <div className="v6-compare"><ComparePanel /></div>
        </>
      ) : (
        <AdvancedNote />
      )}
    </div>
  )
}

function AdvancedNote() {
  const setAdvanced = useBacktest((s) => s.setAdvanced)
  return (
    <p className="v6-adv-note">
      The advanced view adds the full metric list, parameter sweeps, walk-forward, Monte Carlo, a cost ladder, prop-firm
      accounts, custom rules and A/B/C compare.{' '}
      <button type="button" className="v6-link" onClick={() => setAdvanced(true)}>Open advanced view</button>
    </p>
  )
}

function Lower({ advanced }) {
  const activeTab = useBacktest((s) => s.activeTab)
  const setTab = useBacktest((s) => s.setTab)
  const nTrades = useBacktest((s) => s.result?.trades.length)
  const tabRefs = useRef({})

  if (!advanced) {
    return (
      <Section title="Trades" meta={nTrades != null ? `${nTrades}` : null} className="h-full" scroll={false}>
        <Trades />
      </Section>
    )
  }

  const onKeyDown = (e) => {
    const i = TABS.findIndex((t) => t.id === activeTab)
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!d) return
    e.preventDefault()
    const next = TABS[(i + d + TABS.length) % TABS.length]
    setTab(next.id)
    tabRefs.current[next.id]?.focus()
  }

  return (
    <section className="v6-sec h-full" aria-label="Analysis">
      <div className="v6-tabs" role="tablist" aria-label="Analysis" onKeyDown={onKeyDown}>
        {TABS.map((t) => (
          <button
            key={t.id}
            ref={(el) => { tabRefs.current[t.id] = el }}
            type="button"
            role="tab"
            id={`v6-tab-${t.id}`}
            aria-selected={activeTab === t.id}
            aria-controls="v6-tabpanel"
            tabIndex={activeTab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            className="v6-tab"
          >
            {t.label}
            {t.id === 'blotter' && nTrades != null && <span className="num v6-dim"> {nTrades}</span>}
          </button>
        ))}
      </div>
      <div id="v6-tabpanel" role="tabpanel" aria-labelledby={`v6-tab-${activeTab}`} className="v6-sec-body overflow-hidden">
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

/** The original terminal's shortcuts, unchanged: R, [ ], S, W, M, A/B/C, ?,
 *  Esc and Alt+1–4. Plain digits belong to the design switcher. Typing in a
 *  field always wins. */
function useKeyboard() {
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey) return
      const s = useBacktest.getState()
      if (e.altKey) {
        const fam = FAMILIES.find((f) => e.code === `Digit${f.hotkey}`)
        if (fam) {
          e.preventDefault()
          const first = strategiesForPlane(s.plane, s.dataset).find((st) => st.family === fam.id)
          if (first && getStrategy(s.strategyId).family !== fam.id) s.setStrategy(first.id)
        }
        return
      }
      switch (e.key) {
        case 'r':
        case 'R':
          e.preventDefault()
          s.run()
          break
        case '[':
          e.preventDefault()
          s.nudgeFocusedParam(-1)
          break
        case ']':
          e.preventDefault()
          s.nudgeFocusedParam(1)
          break
        case 's':
          s.setAdvanced(true)
          s.setTab('sweep')
          s.runSweep()
          break
        case 'w':
          s.setAdvanced(true)
          s.setTab('wf')
          s.runWalkForward()
          break
        case 'm':
          s.setAdvanced(true)
          s.setTab('mc')
          s.runMonteCarlo()
          break
        case 'a':
        case 'b':
        case 'c':
          s.setAdvanced(true)
          s.saveSlot(e.key.toUpperCase())
          break
        case '?':
          s.toggleShortcuts(true)
          break
        case 'Escape':
          s.togglePalette(false)
          s.toggleShortcuts(false)
          break
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
}
