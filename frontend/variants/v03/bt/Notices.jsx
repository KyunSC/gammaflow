'use client'

import { useBacktest } from '../../../lib/backtest/store'

/** Dataset fallbacks and run errors, said in full above the results. */
export default function Notices() {
  const datasetError = useBacktest((s) => s.datasetError)
  const datasetNotice = useBacktest((s) => s.datasetNotice)
  const setExample = useBacktest((s) => s.setExample)
  const runError = useBacktest((s) => s.runError)
  const configError = useBacktest((s) => s.configError)
  const loadDataset = useBacktest((s) => s.loadDataset)
  const loading = useBacktest((s) => s.datasetLoading)

  if (!datasetNotice && !datasetError && !runError && !configError) return null

  return (
    <div className="v3-notices">
      {datasetNotice && !datasetError && (
        <p className="v3-notice" role="status">
          <span>
            <b>Using the bundled sample.</b> The research dataset service did not answer: {datasetNotice.replace(/ — showing bundled sample data instead\.?$/, '')}.
            Results below are from the sample file in the app, not the latest published data.
          </span>
          <button type="button" onClick={() => setExample(false)} className="btn v3-btn-sm" disabled={loading}>
            {loading ? 'Trying…' : 'Try the server again'}
          </button>
        </p>
      )}
      {datasetError && (
        <p className="v3-notice v3-notice-error" role="alert">
          <span><b>Could not load data.</b> {datasetError}</span>
          <button type="button" onClick={loadDataset} className="btn v3-btn-sm" disabled={loading}>
            {loading ? 'Loading…' : 'Retry'}
          </button>
        </p>
      )}
      {runError && <p className="v3-notice v3-notice-error" role="alert"><span><b>Run failed.</b> {runError}</span></p>}
      {configError && <p className="v3-notice v3-notice-error" role="alert"><span>{configError}</span></p>}
    </div>
  )
}
