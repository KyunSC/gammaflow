const TICK_BAR_SIZES = [10, 25, 50, 100, 250, 500]
const PERIODS = ['1d', '5d', '10d', '14d', '1mo', '3mo', '6mo', '1y', '2y', 'max']
const INTERVALS = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk']

// Valid periods for each interval (based on available seeded data). Same
// table as components/TimeframeSelector.jsx.
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

/** Range, bar size and tick bars as three compact segmented groups. Same
 *  rules as the original selector; tick bars move into a select. */
export default function TimeframeBar({ period, interval, onPeriodChange, onIntervalChange, tickBars, onTickBarsChange }) {
  const periodOff = (p) => (tickBars ? !VALID_PERIODS['1m'].includes(p) : !VALID_PERIODS[interval]?.includes(p))
  const intervalOff = (i) => !!tickBars || !VALID_INTERVALS[period]?.includes(i)

  return (
    <>
      <div className="v4-tf" role="group" aria-label="Range">
        <span className="v4-tf-label">Range</span>
        <div className="v4-seg">
          {PERIODS.map((p) => (
            <button
              key={p}
              aria-pressed={period === p}
              disabled={periodOff(p)}
              title={periodOff(p) ? `Not stored at ${tickBars ? '1m' : interval} bars` : undefined}
              onClick={() => onPeriodChange(p)}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <div className="v4-tf" role="group" aria-label="Bar size">
        <span className="v4-tf-label">Bars</span>
        <div className="v4-seg">
          {INTERVALS.map((i) => (
            <button
              key={i}
              aria-pressed={!tickBars && interval === i}
              disabled={intervalOff(i)}
              title={tickBars ? 'Tick bars are built from 1m bars' : intervalOff(i) ? `Not stored over ${period}` : undefined}
              onClick={() => onIntervalChange(i)}
            >
              {i}
            </button>
          ))}
        </div>
      </div>
      <label className="v4-tf">
        <span className="v4-tf-label">Tick bars</span>
        <select
          className="v4-select"
          value={tickBars ?? ''}
          onChange={(e) => onTickBarsChange(e.target.value === '' ? null : Number(e.target.value))}
        >
          <option value="">Off</option>
          {TICK_BAR_SIZES.map((n) => (
            <option key={n} value={n}>{n}T</option>
          ))}
        </select>
      </label>
    </>
  )
}
