'use client'

import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { useBacktest } from '../../../lib/backtest/store'
import { findGaps } from '../gaps'

/** View-only state for this design. Nothing here changes what a run means,
 *  so it lives outside the shared backtest store. */
export const useV6 = create((set) => ({
  gapOnly: false,
  setGapOnly: (gapOnly) => set({ gapOnly }),
}))

const cache = new WeakMap()

/** Holes in the loaded dataset, computed once per dataset object. */
export function useGaps() {
  const dataset = useBacktest((s) => s.dataset)
  if (!dataset) return null
  if (!cache.has(dataset)) cache.set(dataset, findGaps(dataset))
  return cache.get(dataset)
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const apply = () => setReduced(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  return reduced
}

export function useMedia(query, initial = true) {
  const [match, setMatch] = useState(initial)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const apply = () => setMatch(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [query])
  return match
}
