import { useMemo, useState } from 'react'
import { api, exportUrl, type ExportKind } from '../api/client'
import { ErrorState, Loading } from '../components/States'
import { useResource } from '../hooks'
import { parseCsv } from '../csv'

const DATASETS: { kind: ExportKind; label: string }[] = [
  { kind: 'clips', label: 'Clips' }, { kind: 'activity', label: 'Activity results' },
  { kind: 'engagement', label: 'Visible affect observations' },
  { kind: 'activity-history', label: 'Activity correction history' },
  { kind: 'engagement-history', label: 'Visible affect correction history' },
  { kind: 'annotations', label: 'Staff annotations' }, { kind: 'history', label: 'Staff review history' },
]

export function DataView() {
  const [kind, setKind] = useState<ExportKind>('clips')
  const preview = useResource(() => api.exportCsv(kind), [kind])
  const [columns = [], ...rows] = useMemo(() => parseCsv(preview.data ?? ''), [preview.data])
  const label = DATASETS.find((dataset) => dataset.kind === kind)!.label

  return (
    <>
      <div className="page-head">
        <h1>Data view</h1>
        <details className="menu">
          <summary aria-describedby="export-help">Export</summary>
          <div className="menu__content">
            <p id="export-help" className="muted small">Download database records or staff review data as CSV or JSON.</p>
            <ul>
              {DATASETS.filter((dataset) => dataset.kind !== 'annotations' && dataset.kind !== 'history').map((dataset) =>
                <li key={dataset.kind}>{(['csv', 'json'] as const).map((format) =>
                  <a key={format} href={exportUrl(dataset.kind, format)} download>{dataset.label} ({format.toUpperCase()})</a>)}</li>)}
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
          {DATASETS.map((dataset) => <option key={dataset.kind} value={dataset.kind}>{dataset.label}</option>)}
        </select>
      </label>
      <h2 className="section-title">CSV preview</h2>
      {!preview.loading && preview.data !== undefined && <p className="muted small">Showing {Math.min(rows.length, 200)} of {rows.length} records. Exports include all records.</p>}
      {preview.error && <ErrorState error={preview.error} onRetry={preview.reload} />}
      {preview.loading && <Loading what="CSV preview" />}
      {!preview.loading && preview.data !== undefined && (
        <div className="csv-preview table-wrap" role="region" aria-label="CSV preview" tabIndex={0}>
          <table className="videos" aria-label={`${label} CSV preview`}>
            <thead><tr>{columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr></thead>
            <tbody>
              {rows.slice(0, 200).map((row, index) => <tr key={index}>{row.map((value, column) => <td key={column}>{value}</td>)}</tr>)}
              {rows.length === 0 && <tr><td colSpan={Math.max(columns.length, 1)} className="muted">No records in this dataset yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
