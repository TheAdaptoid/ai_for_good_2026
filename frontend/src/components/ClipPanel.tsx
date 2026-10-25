import { Link } from 'react-router-dom'
import { api, type Annotation, type ReviewClip } from '../api/client'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { StatusBadges } from './StatusBadge'
import { Empty, ErrorState, Loading } from './States'

interface Props {
  clip: ReviewClip
  showRejected: boolean
  version: unknown // changes after any review action so the list re-fetches
  onSelect: (annotation: Annotation) => void
  onClose: () => void
}

export function ClipPanel({ clip, showRejected, version, onSelect, onClose }: Props) {
  const annotations = useResource(() => api.annotations({ clip_id: clip.clip_id, include_rejected: showRejected }),
    [clip.clip_id, showRejected, version])

  return (
    <aside className="panel" aria-label="Review clip">
      <div className="panel__head">
        <h2>Review clip</h2>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close clip panel">×</button>
      </div>
      <dl className="facts">
        <dt>Time</dt><dd>{formatTime(clip.start_seconds)} – {formatTime(clip.end_seconds)}</dd>
        <dt>Review priority</dt>
        <dd>
          {clip.priority_score === null ? 'Not computed' : clip.priority_score.toFixed(2)}
          {clip.priority_method && <span className="muted small"> ({clip.priority_method})</span>}
        </dd>
        <dt>Participants</dt>
        <dd>
          {clip.person_ids.length === 0 ? 'Nobody detected' : clip.person_ids.map((id, i) => (
            <span key={id}>{i > 0 && ', '}<Link to={`/participants/${encodeURIComponent(id)}`}>{id}</Link></span>
          ))}
        </dd>
      </dl>
      <p className="muted small">Review priority ranks clips for attention. It is not a model confidence.</p>
      <h3>Annotations in this clip</h3>
      {annotations.error && <ErrorState error={annotations.error} onRetry={annotations.reload} />}
      {!annotations.data && !annotations.error && <Loading what="clip annotations" />}
      {annotations.data && annotations.data.length === 0 && <Empty>No annotations in this clip.</Empty>}
      {annotations.data && annotations.data.length > 0 && (
        <ul className="clip-annotations">
          {annotations.data.map((a) => (
            <li key={a.annotation_id}>
              <button type="button" className="link" onClick={() => onSelect(a)}>
                {a.label_name} · {a.person_id ?? 'whole clip'}
              </button>
              <span className="muted small"> {a.label_category}
                {a.confidence !== null && ` · model confidence ${a.confidence.toFixed(2)}`}</span>
              <StatusBadges annotation={a} />
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
