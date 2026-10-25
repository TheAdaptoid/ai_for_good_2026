import { Link } from 'react-router-dom'
import { api, type PersonClip } from '../api/client'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { Empty, ErrorState, Loading } from './States'

export function StoredClipPanel({ clip, onClose }: { clip: PersonClip; onClose: () => void }) {
  const summary = useResource(() => api.personClipSummary(clip.clip_id), [clip.clip_id])
  return (
    <aside className="panel" aria-label="Database clip">
      <div className="panel__head">
        <h2>Clip #{clip.clip_id}</h2>
        <button type="button" onClick={onClose}>Close</button>
      </div>
      <p>{formatTime(clip.start_seconds)}–{formatTime(clip.end_seconds)}</p>
      <h3>Participants</h3>
      <ul>{clip.person_ids.map((id) => <li key={id}><Link to={`/participants/${encodeURIComponent(id)}`}>{id}</Link></li>)}</ul>
      <p className="muted small">Stored analysis signals. These records do not carry a staff review status.</p>
      {summary.error && <ErrorState error={summary.error} onRetry={summary.reload} />}
      {!summary.data && !summary.error && <Loading what="clip analysis" />}
      {summary.data && <>
        <h3>Activity</h3>
        {summary.data.dominant_activity === null ? <Empty>No activity results overlap this clip.</Empty> : <>
          <p>{summary.data.dominant_activity}</p>
          <p className="muted small">Share of overlapping activity-window time; not model confidence.</p>
          <dl className="facts">{Object.entries(summary.data.activity_distribution).map(([label, weight]) =>
            <div className="summary-pair" key={label}><dt>{label}</dt><dd>{(weight * 100).toFixed(1)}%</dd></div>)}</dl>
        </>}
        <h3>Visible affect observations</h3>
        {summary.data.visible_affect.observation_count === 0 ? <Empty>No visible-affect scores in this clip.</Empty> : <>
          <p className="muted small">Mean scores across {summary.data.visible_affect.observation_count} available observations. These do not establish internal emotional states.</p>
          <dl className="facts">{(['positive', 'neutral', 'negative'] as const).map((key) =>
            <div className="summary-pair" key={key}><dt>Visible {key} affect</dt><dd>{summary.data!.visible_affect[key]?.toFixed(3) ?? '—'}</dd></div>)}</dl>
        </>}
      </>}
    </aside>
  )
}
