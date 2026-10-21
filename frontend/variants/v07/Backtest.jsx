'use client'

import { useEffect, useState } from 'react'
import { Group as PanelGroup, Panel as RPanel, Separator as PanelResizeHandle } from 'react-resizable-panels'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, FAMILIES, strategiesForPlane } from '../../lib/backtest/strategies'
import { decodeConfig } from '../../lib/backtest/share'
import CommandPalette from '../../components/backtest/CommandPalette'
import TopBar from './bt/TopBar'
import Verdict from './bt/Verdict'
import Setup from './bt/Setup'
import PriceChart from './bt/PriceChart'
import EquityChart from './bt/EquityChart'
import Checks from './bt/Checks'
import Ledger from './bt/Ledger'
import Shortcuts from './bt/Shortcuts'
import { fontVars } from './fonts'
import './v07.css'

/**
 * Run Ledger — the backtester.
 *
 * Reading order is the order of the questions: what did it make next to just
 * holding (verdict), where are the holes in the data, what did the trades look
 * like (price, equity, trade list), and which robustness checks has it been
 * through (tabs). Setup sits on the left; the full metric ledger and compare
 * slots on the right when research tools are on.
 */
export default function Backtest() {
  const advanced = useBacktest((s) => s.advanced)
  const wide = useWide()

  useEffect(() => {
    const store = useBacktest.getState()
    store.restoreUi()
    store.hydrate(decodeConfig(window.location.search))
    store.loadDataset()
  }, [])

  useKeyboard()

  return (
    <div className={`v7 v7-bt ${fontVars}`}>
      <a className="v7-skip" href="#v7-results">Skip to results</a>
      <TopBar />
      <Notices />
      {wide ? (
        <PanelGroup key={advanced ? 'adv' : 'simple'} orientation="horizontal" className="v7-bt-body">
          <RPanel id="v7-setup" defaultSize="21" minSize="15" maxSize="32" className="v7-pane">
            <Setup />
          </RPanel>
          <PanelResizeHandle className="v7-handle v7-handle-x" />
          <RPanel id="v7-main" defaultSize={advanced ? '58' : '79'} minSize="38" className="v7-pane">
            <main id="v7-results" className="v7-main" tabIndex={-1}>
              <Verdict />
              <PanelGroup key={advanced ? "adv" : "simple"} orientation="vertical" className="v7-main-split">
                <RPanel id="v7-price" defaultSize={advanced ? "36" : "40"} minSize="18" className="v7-pane">
                  <PriceChart />
                </RPanel>
                <PanelResizeHandle className="v7-handle v7-handle-y" />
                <RPanel id="v7-eq" defaultSize={advanced ? "21" : "23"} minSize="14" className="v7-pane">
                  <EquityChart />
                </RPanel>
                <PanelResizeHandle className="v7-handle v7-handle-y" />
                <RPanel id="v7-checks" defaultSize={advanced ? "43" : "37"} minSize="14" className="v7-pane">
                  <Checks />
                </RPanel>
              </PanelGroup>
            </main>
          </RPanel>
          {advanced && (
            <>
              <PanelResizeHandle className="v7-handle v7-handle-x" />
              <RPanel id="v7-ledger" defaultSize="21" minSize="16" maxSize="36" className="v7-pane">
                <Ledger />
              </RPanel>
            </>
          )}
        </PanelGroup>
      ) : (
        <div className="v7-bt-stack">
          <main id="v7-results" tabIndex={-1}>
            <Verdict />
            <MobileSetup />
            <div className="v7-h-price"><PriceChart /></div>
            <div className="v7-h-eq"><EquityChart /></div>
            <div className="v7-h-checks"><Checks /></div>
            {advanced && <Ledger />}
          </main>
        </div>
      )}
      <CommandPalette />
      <Shortcuts />
    </div>
  )
}

/** On a phone the setup folds under the verdict, so tweaking a parameter and
 *  reading its effect don't need a scroll past both charts. */
function MobileSetup() {
  const strategyId = useBacktest((s) => s.strategyId)
  const dataset = useBacktest((s) => s.dataset)
  const symbol = useBacktest((s) => (s.plane === 'live' ? s.liveSymbol : s.researchSymbol))
  return (
    <details className="v7-mobile-setup">
      <summary>
        <span className="v7-fold-title">Setup</span>
        <span className="v7-fold-sum">{getStrategy(strategyId).label} on {dataset?.symbol || symbol}</span>
      </summary>
      <Setup />
    </details>
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
    <div className="v7-notices" role="status">
      {datasetNotice && !datasetError && (
        <p className="v7-notice">
          <span>{datasetNotice}</span>
          <button type="button" className="v7-link v7-link-inline" onClick={() => setExample(false)}>Try the server again</button>
        </p>
      )}
      {datasetError && (
        <p className="v7-notice is-error" role="alert">
          <span>Couldn&apos;t load data: {datasetError}</span>
          <button type="button" className="v7-link v7-link-inline" onClick={loadDataset}>Retry</button>
        </p>
      )}
      {runError && <p className="v7-notice is-error" role="alert"><span>Run failed: {runError}</span></p>}
      {configError && <p className="v7-notice is-error" role="alert"><span>{configError}</span></p>}
    </div>
  )
}

function useWide() {
  const [wide, setWide] = useState(true)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const apply = () => setWide(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  return wide
}

/** Same bindings as the original terminal (components/backtest/BacktestTerminal.jsx).
 *  Plain digits and backtick belong to the design switcher; families are Alt+1–4. */
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
