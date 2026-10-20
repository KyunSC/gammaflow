'use client'

import { useBacktest } from '../../../lib/backtest/store'
import { gapsFor } from '../gaps'

export default function useGaps() {
  const dataset = useBacktest((s) => s.dataset)
  return gapsFor(dataset)
}
