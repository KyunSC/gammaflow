'use client'

import './v03.css'
import { useEffect, useState } from 'react'
import { Group, Panel as RPanel, Separator } from 'react-resizable-panels'
import { useBacktest } from '../../lib/backtest/store'
import { getStrategy, FAMILIES, strategiesForPlane } from '../../lib/backtest/strategies'
import { decodeConfig } from '../../lib/backtest/share'
import { fontVars } from './fonts'
import TopBar from './bt/TopBar'
import Notices from './bt/Notices'
import Setup from './bt/Setup'
import Verdict from './bt/Verdict'
import PriceChart from './bt/PriceChart'
import EquityChart from './bt/EquityChart'
import Trades from './bt/Trades'
import Metrics from './bt/Metrics'
import Compare from './bt/Compare'
import Analysis from './bt/Analysis'
import Palette from './bt/Palette'
import Shortcuts from './bt/Shortcuts'
import { Region } from './bt/ui'

/**
 * UI 03, "Research Ledger": the backtester as one ruled sheet.
 * Setup on the left, the result written out (with its caveats) at the top of
 * the main column, then price, equity and trades. Advanced adds the metric
 * table and compare on the right and turns the trade region into tabs.
 * Store, actions and shortcuts are the shared ones.
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
    <div className={`v3-bt ${fontVars}`}>
      <TopBar />
      <Notices />
      {wide ? <WideLayout advanced={advanced} /> : <NarrowLayout advanced={advanced} />}
      <Palette />
      <Shortcuts />
    </div>
  )
}

const SepX = () => <Separator className="v3-sep v3-sep-x" />
const SepY = () => <Separator className="v3-sep v3-sep-y" />

function WideLayout({ advanced }) {
  const lower = advanced ? (
    <Analysis />
  ) : (
    <Region title="Trades" className="v3-fill">
      <Trades />
    </Region>
  )

  return (
    <Group key={advanced ? "adv" : "simple"} orientation="horizontal" className="v3-main">
      <RPanel defaultSize={advanced ? '20' : '22'} minSize="15" maxSize="34" className="v3-col">
        <Setup />
      </RPanel>
      <SepX />
      <RPanel defaultSize={advanced ? '57' : '78'} minSize="35" className="v3-col">
        <div className="v3-center">
          <Verdict />
          <Group orientation="vertical" className="v3-grow-group">
            <RPanel defaultSize="44" minSize="18">
              <PriceChart />
            </RPanel>
            <SepY />
            <RPanel defaultSize="26" minSize="14">
              <EquityChart />
            </RPanel>
            <SepY />
            <RPanel defaultSize="30" minSize="14">
              {lower}
            </RPanel>
          </Group>
        </div>
      </RPanel>
      {advanced && (
        <>
          <SepX />
          <RPanel defaultSize="23" minSize="16" maxSize="38" className="v3-col">
            <Group orientation="vertical">
              <RPanel defaultSize="66" minSize="25">
                <Metrics />
              </RPanel>
              <SepY />
              <RPanel defaultSize="34" minSize="16">
                <Compare />
              </RPanel>
            </Group>
          </RPanel>
        </>
      )}
    </Group>
  )
}

/** Under 1024px: result first, setup after the charts, and a sticky bar so
 *  Run and the setup form are always one tap away. */
function NarrowLayout({ advanced }) {
  const run = useBacktest((s) => s.run)
  const running = useBacktest((s) => s.running)
  const dataset = useBacktest((s) => s.dataset)
  const autoRun = useBacktest((s) => s.autoRun)
  return (
    <>
      <div className="v3-stack v3-scroll" data-scroll>
        <Verdict />
        <div className="v3-h-price"><PriceChart /></div>
        <div className="v3-h-equity"><EquityChart /></div>
        <section className="v3-region" aria-label="Setup"><Setup /></section>
        <div className="v3-h-trades">
          {advanced ? (
            <Analysis />
          ) : (
            <Region title="Trades" className="v3-fill"><Trades /></Region>
          )}
        </div>
        {advanced && (
          <>
            <div className="v3-h-auto"><Metrics /></div>
            <div className="v3-h-auto"><Compare /></div>
          </>
        )}
      </div>
      <div className="v3-dock">
        <a href="#v3-setup" className="btn v3-dock-setup">Edit setup</a>
        <button type="button" onClick={run} disabled={running || !dataset} className="btn btn-primary v3-dock-run">
          {running ? 'Running…' : autoRun ? 'Re-run' : 'Run'}
        </button>
      </div>
    </>
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

/** Same bindings as components/backtest/BacktestTerminal. Plain digits are
 *  left to the design switcher; strategy families are Alt+1–4. */
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
