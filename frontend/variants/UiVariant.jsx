'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { VARIANTS, ORIGINAL, keyToVariantId, findVariant } from './registry'

const STORAGE_KEY = 'ui-variant'
const UiVariantContext = createContext(ORIGINAL)

const readInitial = () => {
  try {
    const q = new URLSearchParams(window.location.search).get('ui')
    if (q) return q === ORIGINAL || q === '00' ? ORIGINAL : q.padStart(2, '0')
    return localStorage.getItem(STORAGE_KEY) || ORIGINAL
  } catch { return ORIGINAL }
}

const isEditable = (el) => {
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || el.isContentEditable
}

/** Holds which design is live. Digits 1–9 and 0 switch to variants 01–10,
 *  backtick goes back to the original. Listens in the capture phase so a
 *  page's own digit shortcuts never see the keypress, and stays out of the
 *  way while a field has focus. */
export function UiVariantProvider({ children }) {
  const [active, setActive] = useState(ORIGINAL)
  const [badge, setBadge] = useState(true)

  useEffect(() => {
    setActive(readInitial())
    try { setBadge(new URLSearchParams(window.location.search).get('badge') !== '0') } catch {}
  }, [])

  useEffect(() => {
    document.documentElement.dataset.ui = active
    try { localStorage.setItem(STORAGE_KEY, active) } catch {}
  }, [active])

  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isEditable(e.target)) return
      const id = keyToVariantId(e.key)
      if (!id) return
      e.preventDefault()
      e.stopImmediatePropagation()
      setActive(id)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  const v = findVariant(active)
  const label = active === ORIGINAL ? 'Original' : `UI ${active}${v?.name ? ` · ${v.name}` : ' · not built'}`

  return (
    <UiVariantContext.Provider value={active}>
      {children}
      {badge && (
        <div className="ui-variant-badge" role="status" aria-live="polite">
          {label}
          <span className="ui-variant-badge-hint"> · keys 1–0, ` original</span>
        </div>
      )}
    </UiVariantContext.Provider>
  )
}

export const useUiVariant = () => useContext(UiVariantContext)

/** The active variant's component for a page slot ('Home' | 'Ticker' |
 *  'Backtest'), or null when the original should render. */
export function useVariantPage(slot) {
  const active = useUiVariant()
  return findVariant(active)?.[slot] || null
}

export { VARIANTS }
