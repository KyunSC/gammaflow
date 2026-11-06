'use client'

import { useState } from 'react'
import { breakOrders, IV_WALL_DEFAULTS } from '../lib/ivWalls'

const etTime = (t) => new Date(t * 1000).toLocaleTimeString('en-US', {
  timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false,
})
const px = (v) => (Number.isFinite(v) ? v.toFixed(2) : '–')
const signedR = (r) => (Number.isFinite(r) ? `${r >= 0 ? '+' : '−'}${Math.abs(r).toFixed(2)}R` : '–')

function statusOf(w, signals) {
  if (!w) return 'No data for this session yet'
  if (w.skip) return `No walls: ${w.skip}`
  if (w.openedOutside) return 'Opened outside the walls: no trade today (backtest rule)'
  const mine = signals.filter(s => s.date === w.date)
  if (!mine.length) return 'Waiting: buy stop at the upper wall, sell stop at the lower wall'
  return mine.map(s => {
    const side = s.side > 0 ? 'Long' : 'Short'
    if (s.exitKind === 'open') return `${side} from ${etTime(s.entryTime)} ET, open (${signedR(s.r)} so far)`
    return `${side} ${etTime(s.entryTime)}–${etTime(s.exitTime)} ET, ${s.exitKind} ${signedR(s.r)}`
  }).join(' · ')
}

/**
 * Today's IV walls, the break orders they imply, and every signal on the bars in view. Reads the result of
 * the chart's `iv-walls` indicator (lib/ivWalls.js).
 */
export default function IvWallsPanel({ result, symbol }) {
  const [copied, setCopied] = useState(false)
  if (!result) {
    return <div className="iv-walls-panel"><p className="iv-note">IV walls: loading closes and {symbol === 'ES=F' ? 'VIX' : 'VXN'}…</p></div>
  }
  const { sessions, signals, signalsOk, params, volSymbol } = result
  const keys = [...sessions.keys()].sort()
  const latest = keys.length ? sessions.get(keys.at(-1)) : null
  const orders = latest && !latest.skip ? breakOrders(latest, params) : null
  const closed = signals.filter(s => s.exitKind !== 'open')
  const avgR = closed.length ? closed.reduce((a, s) => a + s.r, 0) / closed.length : NaN
  const tested = params.stopSigma === IV_WALL_DEFAULTS.stopSigma && params.targetR === IV_WALL_DEFAULTS.targetR
  const volName = volSymbol?.replace('^', '') || 'VOL'

  const copyCsv = async () => {
    const rows = [['date', 'side', 'entry_time_et', 'entry', 'stop', 'target', 'exit_time_et', 'exit', 'exit_kind', 'r']]
    for (const s of signals) {
      rows.push([s.date, s.side > 0 ? 'long' : 'short', etTime(s.entryTime), px(s.entry), px(s.stop), px(s.target),
        s.exitTime ? etTime(s.exitTime) : '', px(s.exit), s.exitKind, Number.isFinite(s.r) ? s.r.toFixed(3) : ''])
    }
    try {
      await navigator.clipboard.writeText(rows.map(r => r.join(',')).join('\n'))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch { setCopied(false) }
  }

  return (
    <div className="iv-walls-panel">
      <div className="iv-head">
        <h3>IV Walls · {latest?.date || '–'}</h3>
        <span className={`iv-chip${tested ? '' : ' warn'}`}>
          {tested ? 'Tested rules' : 'Changed from tested 0.4σ / 2R'}: stop {params.stopSigma}σ, target {params.targetR}R, flat 15:55
        </span>
      </div>
      {latest && !latest.skip && (
        <div className="iv-grid">
          <div><span>Prior close</span><b>{px(latest.pc)}</b><small>{latest.pcDate}</small></div>
          <div><span>{volName}</span><b>{latest.vol.toFixed(2)}</b><small>{latest.volDate}</small></div>
          <div><span>σ implied / hist</span><b>{latest.sigmaIv.toFixed(1)} / {latest.sigmaHv.toFixed(1)}</b><small>points</small></div>
          <div><span>σ (blend)</span><b>{latest.sigma.toFixed(1)}</b><small>{(100 * latest.sigma / latest.pc).toFixed(2)}% of price</small></div>
          <div className="up"><span>Long · buy stop</span><b>{px(orders.long.entry)}</b><small>stop {px(orders.long.stop)} · target {px(orders.long.target)}</small></div>
          <div className="down"><span>Short · sell stop</span><b>{px(orders.short.entry)}</b><small>stop {px(orders.short.stop)} · target {px(orders.short.target)}</small></div>
        </div>
      )}
      <p className="iv-status">{statusOf(latest, signals)}</p>
      {!signalsOk && <p className="iv-note">Signals need 1m or 5m bars; walls are drawn on any intraday timeframe.</p>}
      {signalsOk && signals.length > 0 && (
        <>
          <div className="iv-table-wrap">
            <table className="iv-table">
              <thead><tr><th>Date</th><th>Side</th><th>Entry (ET)</th><th>Entry</th><th>Stop</th><th>Target</th><th>Exit</th><th>Result</th></tr></thead>
              <tbody>
                {[...signals].reverse().map(s => (
                  <tr key={`${s.date}-${s.wall}`}>
                    <td>{s.date}</td>
                    <td className={s.side > 0 ? 'up' : 'down'}>{s.side > 0 ? 'Long' : 'Short'}</td>
                    <td>{etTime(s.entryTime)}</td>
                    <td>{px(s.entry)}</td>
                    <td>{px(s.stop)}</td>
                    <td>{px(s.target)}</td>
                    <td>{s.exitKind === 'open' ? 'open' : `${s.exitKind} ${etTime(s.exitTime)}`}</td>
                    <td className={s.r > 0 ? 'up' : s.r < 0 ? 'down' : ''}>{signedR(s.r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="iv-foot">
            <span>{closed.length} closed in view · average {signedR(avgR)} before costs</span>
            <button type="button" onClick={copyCsv}>{copied ? 'Copied' : 'Copy CSV'}</button>
          </div>
        </>
      )}
      <p className="iv-note">
        Replays the backtest on the chart’s bars: decisions on every bar (backtest: 5-minute closes), Yahoo’s continuous
        contract, no walls on the first session after a quarterly expiry, stop assumed first when stop and target share a bar.
        Results are before costs (about 0.02R per trade on MNQ at 0.4σ).
      </p>
    </div>
  )
}
