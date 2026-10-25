import { useState, type FormEvent } from 'react'
import { api, type Annotation, type EditRequest, type Label, type ReviewAction, type ReviewEvent } from '../api/client'
import { formatTime, toFrame, toSeconds } from '../format'
import { useResource } from '../hooks'
import { StatusBadges } from './StatusBadge'
import { ErrorState, Loading } from './States'

interface Props {
  annotation: Annotation
  labels: Label[]
  fps: number
  participantIds: string[]
  onChanged: (annotation: Annotation) => void
  onClose: () => void
}

export function ReviewPanel({ annotation, labels, fps, participantIds, onChanged, onClose }: Props) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const history = useResource(() => api.history(annotation.annotation_id), [annotation.annotation_id])

  async function run(action: () => Promise<{ annotation: Annotation }>) {
    setBusy(true)
    setError(null)
    try {
      const result = await action()
      setNote('')
      setEditing(false)
      history.reload() // updated_at has 1 s resolution, so it cannot signal back-to-back actions
      onChanged(result.annotation)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const review = (action: ReviewAction) => run(() => api.review(annotation.annotation_id, action, note || null))

  return (
    <aside className="panel" aria-label="Review annotation">
      <div className="panel__head">
        <h2>{annotation.label_name}</h2>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close review panel">×</button>
      </div>
      <StatusBadges annotation={annotation} />
      <dl className="facts">
        <dt>Category</dt><dd>{annotation.label_category}</dd>
        <dt>Time</dt><dd>{formatTime(annotation.start_seconds)} – {formatTime(annotation.end_seconds)}</dd>
        <dt>Participant</dt><dd>{annotation.person_id ?? 'Whole scene'}</dd>
        <dt>Model confidence</dt>
        <dd>{annotation.confidence === null ? 'None (human value)' : annotation.confidence.toFixed(2)}</dd>
        {annotation.clip_id !== null && <><dt>Review clip</dt><dd>#{annotation.clip_id}</dd></>}
      </dl>

      {editing ? (
        <EditForm annotation={annotation} labels={labels} fps={fps} participantIds={participantIds}
          note={note} busy={busy} onCancel={() => setEditing(false)}
          onSubmit={(body) => run(() => api.edit(annotation.annotation_id, { ...body, note: note || null }))}
          onNote={setNote} />
      ) : (
        <div className="review-actions">
          <label>
            Note (optional)
            <textarea value={note} rows={2} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="button-row">
            <button type="button" className="primary" disabled={busy} onClick={() => void review('accept')}>Accept</button>
            <button type="button" disabled={busy} onClick={() => setEditing(true)}>Edit…</button>
            <button type="button" disabled={busy} onClick={() => void review('defer')}>Defer</button>
            <button type="button" className="danger" disabled={busy} onClick={() => void review('reject')}>Reject</button>
          </div>
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}

      <h3>History</h3>
      {history.error && <ErrorState error={history.error} onRetry={history.reload} />}
      {!history.data && !history.error && <Loading what="history" />}
      {history.data && history.data.length === 0 && <p className="muted">No review actions yet.</p>}
      {history.data && history.data.length > 0 && (
        <ol className="history">
          {history.data.map((event) => <HistoryEntry key={event.event_id} event={event} labels={labels} fps={fps} />)}
        </ol>
      )}
    </aside>
  )
}

function EditForm({ annotation, labels, fps, participantIds, note, busy, onCancel, onSubmit, onNote }: {
  annotation: Annotation; labels: Label[]; fps: number; participantIds: string[]; note: string; busy: boolean
  onCancel: () => void; onSubmit: (body: EditRequest) => void; onNote: (note: string) => void
}) {
  const [labelId, setLabelId] = useState(annotation.label_id)
  const [start, setStart] = useState(String(annotation.start_seconds?.toFixed(2) ?? ''))
  const [end, setEnd] = useState(String(annotation.end_seconds?.toFixed(2) ?? ''))
  const [person, setPerson] = useState(annotation.person_id ?? '')
  const [problem, setProblem] = useState<string | null>(null)
  // Only active labels of the same category may be newly applied; the current one stays listed.
  const choices = labels.filter((l) => l.category === annotation.label_category
    && (l.is_active || l.label_id === annotation.label_id))
  const people = annotation.person_id && !participantIds.includes(annotation.person_id)
    ? [annotation.person_id, ...participantIds] : participantIds

  function submit(event: FormEvent) {
    event.preventDefault()
    const startFrame = toFrame(Number(start), fps)
    const endFrame = toFrame(Number(end), fps)
    if (!Number.isFinite(startFrame) || !Number.isFinite(endFrame) || endFrame < startFrame) {
      setProblem('End must be at or after start.')
      return
    }
    const body: EditRequest = {}
    if (labelId !== annotation.label_id) body.label_id = labelId
    if (startFrame !== annotation.start_frame) body.start_frame = startFrame
    if (endFrame !== annotation.end_frame) body.end_frame = endFrame
    if ((person || null) !== annotation.person_id) body.person_id = person || null
    setProblem(null)
    onSubmit(body)
  }

  return (
    <form className="edit-form" onSubmit={submit}>
      <label>
        Label
        <select value={labelId} onChange={(e) => setLabelId(Number(e.target.value))}>
          {choices.map((l) => (
            <option key={l.label_id} value={l.label_id}>{l.name}{l.is_active ? '' : ' (inactive)'}</option>
          ))}
        </select>
      </label>
      <div className="field-pair">
        <label>Start (s)<input type="number" step="0.01" min="0" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label>End (s)<input type="number" step="0.01" min="0" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
      </div>
      <label>
        Participant
        <select value={person} onChange={(e) => setPerson(e.target.value)}>
          <option value="">Whole scene (no participant)</option>
          {people.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
      </label>
      <label>Note (optional)<textarea value={note} rows={2} onChange={(e) => onNote(e.target.value)} /></label>
      {problem && <p className="form-error" role="alert">{problem}</p>}
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy}>Save edit</button>
        <button type="button" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
      <p className="muted small">Changing a value makes the source HUMAN. Saving with no changes counts as Accept.</p>
    </form>
  )
}

function HistoryEntry({ event, labels, fps }: { event: ReviewEvent; labels: Label[]; fps: number }) {
  const name = (id: number | null) => labels.find((l) => l.label_id === id)?.name ?? (id === null ? '—' : `#${id}`)
  const span = (s: number | null, e: number | null) => s === null || e === null ? '—'
    : `${formatTime(toSeconds(s, fps))}–${formatTime(toSeconds(e, fps))}`
  const changes: string[] = []
  if (event.prev_label_id !== event.new_label_id) changes.push(`label ${name(event.prev_label_id)} → ${name(event.new_label_id)}`)
  if (event.prev_start_frame !== event.new_start_frame || event.prev_end_frame !== event.new_end_frame) {
    changes.push(`time ${span(event.prev_start_frame, event.prev_end_frame)} → ${span(event.new_start_frame, event.new_end_frame)}`)
  }
  if (event.prev_person_id !== event.new_person_id) {
    changes.push(`participant ${event.prev_person_id ?? 'none'} → ${event.new_person_id ?? 'none'}`)
  }
  if (event.prev_source !== event.new_source) changes.push(`source ${event.prev_source ?? '—'} → ${event.new_source}`)
  return (
    <li>
      <strong>{event.action}</strong> by {event.reviewer_id}
      <span className="muted"> · {new Date(event.created_at).toLocaleString()}</span>
      {event.action === 'CREATED' && <div>{name(event.new_label_id)}, {span(event.new_start_frame, event.new_end_frame)}</div>}
      {event.action !== 'CREATED' && changes.length > 0 && <div>{changes.join('; ')}</div>}
      {event.prev_confidence !== null && event.new_confidence === null && (
        <div className="muted small">original model confidence {event.prev_confidence.toFixed(2)}</div>
      )}
      {event.note && <div className="note">“{event.note}”</div>}
    </li>
  )
}
