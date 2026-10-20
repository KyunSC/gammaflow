'use client'

import { useEffect } from 'react'
import { Command } from 'cmdk'
import { useBacktest } from '../../../lib/backtest/store'
import { strategiesForPlane, getStrategy } from '../../../lib/backtest/strategies'
import { LIVE_SYMBOLS, LIVE_INTERVALS, LIVE_PERIODS } from '../../../lib/backtest/datasets'

/**
 * ⌘K. Everything reachable by mouse is reachable here, including the parameter
 * list — which is generated from the strategy schema, so it never falls behind
 * the panel it mirrors.
 */
export default function CommandPalette() {
  const open = useBacktest((s) => s.paletteOpen)
  const togglePalette = useBacktest((s) => s.togglePalette)
  const plane = useBacktest((s) => s.plane)
  const strategyId = useBacktest((s) => s.strategyId)
  const dataset = useBacktest((s) => s.dataset)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        togglePalette()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [togglePalette])

  if (!open) return null

  const s = useBacktest.getState()
  const strategy = getStrategy(strategyId)
  const close = () => togglePalette(false)
  const act = (fn) => () => {
    fn()
    close()
  }

  return (
    <div className="v3-overlay v3-overlay-top" onClick={close}>
      <Command
        label="Command palette"
        onClick={(e) => e.stopPropagation()}
        // The global shortcut handler ignores keys typed into inputs, and the
        // palette's search box is one — so Escape has to be handled here or the
        // overlay stays up and swallows every click behind it.
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation()
            close()
          }
        }}
        className="v3-dialog v3-palette"
        loop
      >
        <Command.Input
          autoFocus
          placeholder="Run, switch strategy, jump to a parameter…"
          className="v3-palette-input"
        />
        <Command.List className="v3-palette-list">
          <Command.Empty className="v3-empty"><p>Nothing matches.</p></Command.Empty>

          <Group heading="run">
            <Item onSelect={act(s.run)} shortcut="R">Run backtest</Item>
            <Item onSelect={act(s.runSweep)}>Run parameter sweep</Item>
            <Item onSelect={act(s.runWalkForward)}>Run walk-forward</Item>
            <Item onSelect={act(s.runMonteCarlo)}>Run Monte Carlo</Item>
            <Item onSelect={act(() => { s.setAdvanced(true); s.setTab('costs'); s.runCostCurve() })}>Run cost ladder</Item>
            <Item onSelect={act(s.toggleAutoRun)}>Toggle auto-run on parameter change</Item>
            <Item onSelect={act(() => s.setAdvanced(!s.advanced))}>{s.advanced ? 'Switch to the simple view' : 'Open the advanced view'}</Item>
          </Group>

          <Group heading="strategy">
            {strategiesForPlane(plane, dataset).map((st) => (
              <Item key={st.id} onSelect={act(() => s.setStrategy(st.id))} active={st.id === strategyId}>
                {st.label} <span className="v3-dim">— {st.blurb}</span>
              </Item>
            ))}
          </Group>

          <Group heading="parameters">
            {strategy.params
              .filter((p) => !p.hidden && p.type === 'number')
              .map((p) => (
                <Item
                  key={p.key}
                  onSelect={act(() => s.setFocusedParam(p.key))}
                  shortcut="[ ]"
                >
                  Focus {p.label} <span className="v3-dim">= {s.currentParams()[p.key]}</span>
                </Item>
              ))}
          </Group>

          <Group heading="dataset">
            <Item onSelect={act(() => s.setPlane('research'))} active={plane === 'research'}>
              Research plane — historical GEX + model predictions
            </Item>
            <Item onSelect={act(() => s.setPlane('live'))} active={plane === 'live'}>
              Live plane — /api/historical
            </Item>
            {plane === 'research'
              ? ['QQQ', 'SPY'].map((sym) => (
                  <Item key={sym} onSelect={act(() => s.setResearchSymbol(sym))}>
                    Load {sym} research dataset
                  </Item>
                ))
              : LIVE_SYMBOLS.map((sym) => (
                  <Item key={sym} onSelect={act(() => s.setLive({ liveSymbol: sym }))}>
                    Load {sym}
                  </Item>
                ))}
            {plane === 'live' &&
              LIVE_INTERVALS.map((iv) => (
                <Item key={iv} onSelect={act(() => s.setLive({ liveInterval: iv }))}>
                  Interval {iv}
                </Item>
              ))}
            {plane === 'live' &&
              LIVE_PERIODS.map((p) => (
                <Item key={p} onSelect={act(() => s.setLive({ livePeriod: p }))}>
                  Period {p}
                </Item>
              ))}
          </Group>

          <Group heading="panels">
            {[
              ['blotter', 'Trade blotter'],
              ['sweep', 'Parameter sweep'],
              ['wf', 'Walk-forward'],
              ['mc', 'Monte Carlo'],
              ['costs', 'Cost sensitivity'],
              ['rules', 'Rule builder'],
            ].map(([id, label]) => (
              <Item key={id} onSelect={act(() => { s.setAdvanced(true); s.setTab(id) })}>
                Show {label}
              </Item>
            ))}
          </Group>

          <Group heading="compare">
            {['A', 'B', 'C'].map((slot) => (
              <Item key={slot} onSelect={act(() => s.saveSlot(slot))}>
                Pin current run to slot {slot}
              </Item>
            ))}
          </Group>

          <Group heading="sweep cells">
            {(s.sweep.data?.cells || [])
              .slice()
              .sort((a, b) => b.sharpe - a.sharpe)
              .slice(0, 8)
              .map((c, i) => (
                <Item key={i} onSelect={act(() => s.applySweepCell(c))}>
                  Load {s.sweep.xKey}={c.x}, {s.sweep.yKey}={c.y}{' '}
                  <span className="v3-dim">— Sharpe {c.sharpe.toFixed(2)}</span>
                </Item>
              ))}
          </Group>
        </Command.List>
      </Command>
    </div>
  )
}

function Group({ heading, children }) {
  return (
    <Command.Group
      heading={heading}
      className="v3-palette-group"
    >
      {children}
    </Command.Group>
  )
}

function Item({ children, onSelect, shortcut, active }) {
  return (
    <Command.Item
      onSelect={onSelect}
      className={`v3-palette-item ${active ? 'is-active' : ''}`}
    >
      <span className="v3-palette-text">{children}</span>
      {shortcut && <span className="kbd">{shortcut}</span>}
    </Command.Item>
  )
}
