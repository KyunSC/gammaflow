'use client'

import { useMemo } from 'react'
import { getStrategy } from '../../lib/backtest/strategies'

/**
 * The strategy's prepared state for the last run, rebuilt on the main thread
 * from the run's own config (not the current controls, which may have moved
 * since). Series come from the dataset's cache, so this is cheap after the
 * first call. Returns null when the run and the loaded dataset disagree.
 */
export default function useStrategyState(result, dataset) {
  return useMemo(() => {
    if (!result || !dataset || result.config.datasetId !== dataset.id) return null
    const strategy = getStrategy(result.config.strategyId)
    if (!strategy.prepare) return null
    try {
      return strategy.prepare(dataset, result.config.params)
    } catch {
      return null
    }
  }, [result, dataset])
}
