'use client'

import s from './site.module.css'

// Same options and validity tables as components/TimeframeSelector.jsx; laid
// out as three labelled segmented rows on one line instead of loose buttons.
const TICK_BAR_SIZES = [10, 25, 50, 100, 250, 500]
const PERIODS = ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y', 'max']
const INTERVALS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk']
const VALID_PERIODS = {
  '1m': ['1d', '5d'],
  '5m': ['1d', '5d', '10d', '14d', '1mo', '3mo'],
  '15m': ['1d', '5d', '10d', '14d', '1mo', '3mo'],
  '30m': ['1d', '5d', '10d', '14d', '1mo', '3mo'],
  '1h': ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y'],
  '4h': ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y'],
  '1d': ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y', 'max'],
  '1wk': ['1mo', '3mo', '6mo', '1y', '2y', 'max'],
}
const VALID_INTERVALS = {}
for (const p of PERIODS) VALID_INTERVALS[p] = INTERVALS.filter((i) => VALID_PERIODS[i]?.includes(p))

export default function Timeframe({ period, interval, onPeriodChange, onIntervalChange, tickBars, onTickBarsChange }) {
  const periodOff = (p) => (tickBars ? !VALID_PERIODS['1m']?.includes(p) : !VALID_PERIODS[interval]?.includes(p))
  const intervalOff = (i) => !!tickBars || !VALID_INTERVALS[period]?.includes(i)

  return (
    <div className={s.tf}>
      <Seg label="Range" items={PERIODS} value={period} off={periodOff} onPick={onPeriodChange} />
      <Seg label="Bars" items={INTERVALS} value={tickBars ? null : interval} off={intervalOff} onPick={onIntervalChange} />
      <Seg
        label="Tick bars"
        items={['off', ...TICK_BAR_SIZES]}
        value={tickBars ?? 'off'}
        off={() => false}
        onPick={(v) => onTickBarsChange(v === 'off' ? null : v)}
        fmt={(v) => (v === 'off' ? 'off' : `${v}T`)}
        title="Groups N one-minute bars into one bar; switches the chart to 1m data"
      />
    </div>
  )
}

function Seg({ label, items, value, off, onPick, fmt = (v) => v, title }) {
  return (
    <div className={s.seg} role="group" aria-label={label} title={title}>
      <span className={s.segLabel}>{label}</span>
      {items.map((v) => (
        <button
          key={v}
          disabled={off(v)}
          aria-pressed={value === v}
          className={`${s.segBtn} ${value === v ? s.segOn : ''}`}
          onClick={() => onPick(v)}
        >
          {fmt(v)}
        </button>
      ))}
    </div>
  )
}
