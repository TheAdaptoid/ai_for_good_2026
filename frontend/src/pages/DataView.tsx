import { useState } from 'react'
import { api, exportUrl, type ExportKind } from '../api/client'
import { ErrorState, Loading } from '../components/States'
import { useResource } from '../hooks'

export function DataView() {
  const [kind, setKind] = useState<ExportKind>('annotations')
  const preview = useResource(() => api.exportCsv(kind), [kind])

  return (
    <>
      <div className="page-head">
        <h1>Data view</h1>
        <details className="menu">
          <summary aria-describedby="export-help">Export</summary>
          <div className="menu__content">
            <p id="export-help" className="muted small">Download current annotations or review history as CSV or JSON.</p>
            <ul>
              <li><a href={exportUrl('annotations', 'csv')} download>Annotations (CSV)</a></li>
              <li><a href={exportUrl('annotations', 'json')} download>Annotations (JSON)</a></li>
              <li><a href={exportUrl('history', 'csv')} download>Review history (CSV)</a></li>
              <li><a href={exportUrl('history', 'json')} download>Review history (JSON)</a></li>
            </ul>
          </div>
        </details>
      </div>
      <p className="muted">Preview the CSV generated from the current database. With no records, only column headers appear.</p>
      <label className="data-view__dataset">
        Dataset
        <select value={kind} onChange={(event) => setKind(event.target.value as ExportKind)}>
          <option value="annotations">Annotations</option>
          <option value="history">Review history</option>
        </select>
      </label>
      <h2 className="section-title">CSV preview</h2>
      {preview.error && <ErrorState error={preview.error} onRetry={preview.reload} />}
      {preview.loading && <Loading what="CSV preview" />}
      {!preview.loading && preview.data !== undefined && (
        <pre className="csv-preview" role="region" aria-label="CSV preview" tabIndex={0}>{preview.data}</pre>
      )}
    </>
  )
}
