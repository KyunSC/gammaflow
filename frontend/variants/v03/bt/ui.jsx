'use client'

import { useId } from 'react'
import { useBacktest } from '../../../lib/backtest/store'

/**
 * A ruled region: a title line and a body, sharing edges with its neighbours.
 * No card, no shadow, no entrance animation; the hairline does the grouping.
 */
export function Region({ title, aside, children, className = '', bodyClassName = '', scroll = false, id, as: Tag = 'section' }) {
  const hid = useId()
  return (
    <Tag className={`v3-region ${className}`} aria-labelledby={title ? hid : undefined} id={id}>
      {title && (
        <header className="v3-region-head">
          <h2 id={hid} className="v3-region-title">{title}</h2>
          {aside && <div className="v3-region-aside">{aside}</div>}
        </header>
      )}
      <div className={`v3-region-body ${scroll ? 'v3-scroll' : ''} ${bodyClassName}`}>{children}</div>
    </Tag>
  )
}

export function Empty({ children, action, tone }) {
  return (
    <div className={`v3-empty ${tone === 'error' ? 'v3-empty-error' : ''}`} role={tone === 'error' ? 'alert' : undefined}>
      <p>{children}</p>
      {action}
    </div>
  )
}

/** What the user should do next when there is no result to draw. */
export function NoResult({ what = 'Results' }) {
  const loading = useBacktest((s) => s.datasetLoading)
  const running = useBacktest((s) => s.running)
  const autoRun = useBacktest((s) => s.autoRun)
  const datasetError = useBacktest((s) => s.datasetError)
  if (datasetError) return <Empty>No data loaded, so there is nothing to show.</Empty>
  if (loading) return <Empty>Loading bars…</Empty>
  if (running) return <Empty>Running…</Empty>
  return <Empty>{autoRun ? `${what} appear after the first run.` : `Press Run (R) to see ${what.toLowerCase()}.`}</Empty>
}

export function Switch({ checked, onChange, label, title }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={Boolean(checked)}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className="switch"
      title={title}
    />
  )
}

/** `options` for a flat list, or `groups: [{ label, options }]` for <optgroup>s. */
export function Select({ value, onChange, options, groups, label, id }) {
  const norm = (list) => list.map((o) => (typeof o === 'string' ? { value: o, label: o } : o))
  const renderOpts = (list) =>
    norm(list).map((o) => (
      <option key={o.value} value={o.value} disabled={o.disabled}>
        {o.label}
      </option>
    ))
  return (
    <span className="v3-select">
      <select id={id} aria-label={id ? undefined : label} value={value} onChange={(e) => onChange(e.target.value)} className="field">
        {groups
          ? groups.map((g) => (
              <optgroup key={g.label} label={g.label}>
                {renderOpts(g.options)}
              </optgroup>
            ))
          : renderOpts(options)}
      </select>
    </span>
  )
}

/** Label, slider and exact number in one row, all tied to the same name. */
export function NumRow({ label, value, min, max, step, onChange, hint, focused, onFocus }) {
  const id = useId()
  return (
    <div className={`v3-num ${focused ? 'is-focused' : ''}`} onMouseDown={onFocus} title={hint}>
      <label htmlFor={id} className="v3-num-label">{label}</label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-label={label}
        tabIndex={-1}
        onChange={(e) => onChange(Number(e.target.value))}
        className="v3-range"
      />
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onFocus={onFocus}
        onChange={(e) => onChange(Number(e.target.value))}
        className="field v3-num-input"
      />
      {hint && focused && <span className="v3-num-hint">{hint}</span>}
    </div>
  )
}

export function Segmented({ value, onChange, options, label }) {
  return (
    <div className="v3-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          type="button"
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`v3-seg-btn ${value === o.value ? 'is-on' : ''}`}
          title={o.title}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
