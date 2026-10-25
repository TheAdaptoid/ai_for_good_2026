import { useState, type FormEvent } from 'react'
import { api, type ClipEditRequest, type PersonClip } from '../api/client'
import { useResource } from '../hooks'
import { ErrorState, Loading } from './States'

const SCORES = ['positive', 'neutral', 'negative'] as const
const OTHER = '__other__'

/** Staff review of a stored clip: Accept or Defer set its status; Edit corrects its stored signals. */
export function ClipReviewWidget({ clip, onReviewed }: {
  clip: PersonClip; onReviewed: (status: 'ACCEPTED' | 'EDITED' | 'DEFERRED') => void
}) {
  const labels = useResource(api.labels, [])
  const summary = useResource(() => api.personClipSummary(clip.clip_id), [clip.clip_id])
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(action: () => Promise<unknown>, status: 'ACCEPTED' | 'EDITED' | 'DEFERRED') {
    setBusy(true)
    setError(null)
    try {
      await action()
      setEditing(false)
      onReviewed(status)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel clip-review-widget" aria-label="Review this clip">
      <div className="panel__head">
        <h2>Review</h2>
        <span className={`badge badge--status-${clip.review_status.toLowerCase()}`} title="Review status">{clip.review_status}</span>
      </div>
      {(labels.error || summary.error) && <ErrorState error={(labels.error ?? summary.error)!} onRetry={() => { labels.reload(); summary.reload() }} />}
      {(!labels.data || !summary.data) && !labels.error && !summary.error && <Loading what="review options" />}
      {labels.data && summary.data && (editing ? (
        <EditForm
          activityLabels={labels.data.filter((l) => l.category === 'activity' && l.is_active).map((l) => l.name)}
          current={summary.data.dominant_activity}
          scores={summary.data.visible_affect}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSubmit={(body) => void run(() => api.editPersonClip(clip.clip_id, body), 'EDITED')} />
      ) : (
        <div className="button-row">
          <button type="button" className="primary" disabled={busy} onClick={() => void run(() => api.reviewPersonClip(clip.clip_id, 'accept'), 'ACCEPTED')}>Accept</button>
          <button type="button" disabled={busy} onClick={() => setEditing(true)}>Edit…</button>
          <button type="button" disabled={busy} onClick={() => void run(() => api.reviewPersonClip(clip.clip_id, 'defer'), 'DEFERRED')}>Defer</button>
        </div>
      ))}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  )
}

function EditForm({ activityLabels, current, scores, busy, onCancel, onSubmit }: {
  activityLabels: string[]; current: string | null
  scores: Record<(typeof SCORES)[number], number | null>; busy: boolean
  onCancel: () => void; onSubmit: (body: ClipEditRequest) => void
}) {
  const initial = Object.fromEntries(SCORES.map((key) => [key, scores[key]?.toFixed(3) ?? ''])) as Record<(typeof SCORES)[number], string>
  const [label, setLabel] = useState('')
  const [otherName, setOtherName] = useState('')
  const [values, setValues] = useState(initial)
  const [problem, setProblem] = useState<string | null>(null)

  function submit(event: FormEvent) {
    event.preventDefault()
    const body: ClipEditRequest = {}
    if (label === OTHER) {
      const name = otherName.trim()
      if (!name) {
        setProblem('Type a name for the new activity label.')
        return
      }
      // An existing label typed by hand is reused rather than duplicated.
      const existing = activityLabels.find((known) => known.toLowerCase() === name.toLowerCase())
      body.activity_label = existing ?? name
      if (!existing) body.create_activity_label = true
    } else if (label) body.activity_label = label
    if (SCORES.some((key) => values[key] !== initial[key])) {
      const numbers = SCORES.map((key) => Number(values[key]))
      if (SCORES.some((key) => values[key] === '') || numbers.some((n) => !(n >= 0 && n <= 1))) {
        setProblem('Each visible-affect score must be between 0 and 1.')
        return
      }
      ;[body.positive_score, body.neutral_score, body.negative_score] = numbers
    }
    if (Object.keys(body).length === 0) {
      setProblem('Choose a new activity label or change a score.')
      return
    }
    setProblem(null)
    onSubmit(body)
  }

  return (
    <form className="edit-form" onSubmit={submit}>
      <label>
        Activity label
        <select value={label} onChange={(e) => setLabel(e.target.value)}>
          <option value="">Keep current ({current ?? 'none'})</option>
          {activityLabels.map((name) => <option key={name} value={name}>{name}</option>)}
          <option value={OTHER}>Other…</option>
        </select>
      </label>
      {label === OTHER && (
        <label>
          New activity label
          <input type="text" maxLength={200} value={otherName} autoFocus onChange={(e) => setOtherName(e.target.value)} />
          <span className="muted small">Adds a reusable staff label and assigns it only to this clip's frames. Model predictions stay unchanged.</span>
        </label>
      )}
      <fieldset className="field-trio">
        <legend>Visible affect scores (0–1)</legend>
        {SCORES.map((key) => (
          <label key={key}>
            Visible {key}
            <input type="number" step="0.001" min="0" max="1" value={values[key]}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
          </label>
        ))}
      </fieldset>
      <p className="muted small">
        Saving records a human activity annotation only for this clip's frames. Model activity predictions
        stay unchanged. Changed visible-affect scores apply to this clip's members and remain audited.
      </p>
      {problem && <p className="form-error" role="alert">{problem}</p>}
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy}>Save edit</button>
        <button type="button" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}
