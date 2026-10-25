import { useState, type FormEvent } from 'react'
import { api, type Annotation, type Label } from '../api/client'
import { toFrame } from '../format'

interface Props {
  videoId: number
  fps: number
  labels: Label[]
  participantIds: string[]
  currentTime: () => number
  onCreated: (annotation: Annotation) => void
  onClose: () => void
}

export function CreateForm({ videoId, fps, labels, participantIds, currentTime, onCreated, onClose }: Props) {
  const active = labels.filter((l) => l.is_active)
  const [labelId, setLabelId] = useState(active[0]?.label_id ?? 0)
  const [start, setStart] = useState(currentTime().toFixed(2))
  const [end, setEnd] = useState((currentTime() + 5).toFixed(2))
  const [person, setPerson] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const startFrame = toFrame(Number(start), fps)
    const endFrame = toFrame(Number(end), fps)
    if (!Number.isFinite(startFrame) || !Number.isFinite(endFrame) || endFrame < startFrame) {
      setError('End must be at or after start.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await api.create({
        video_id: videoId, label_id: labelId, start_frame: startFrame, end_frame: endFrame,
        person_id: person || null, note: note || null,
      })
      onCreated(result.annotation)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const group = (category: string) => active.filter((l) => l.category === category)
  return (
    <aside className="panel" aria-label="Add annotation">
      <div className="panel__head">
        <h2>Add annotation</h2>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close">×</button>
      </div>
      <p className="muted small">For a moment the pipeline missed. It is saved as source HUMAN, status ACCEPTED.</p>
      <form className="edit-form" onSubmit={submit}>
        <label>
          Label
          <select value={labelId} onChange={(e) => setLabelId(Number(e.target.value))}>
            <optgroup label="Activities">
              {group('activity').map((l) => <option key={l.label_id} value={l.label_id}>{l.name}</option>)}
            </optgroup>
            <optgroup label="Observations">
              {group('observation').map((l) => <option key={l.label_id} value={l.label_id}>{l.name}</option>)}
            </optgroup>
          </select>
        </label>
        <div className="field-pair">
          <label>
            Start (s)
            <input type="number" step="0.01" min="0" value={start} onChange={(e) => setStart(e.target.value)} />
            <button type="button" className="link" onClick={() => setStart(currentTime().toFixed(2))}>Use current time</button>
          </label>
          <label>
            End (s)
            <input type="number" step="0.01" min="0" value={end} onChange={(e) => setEnd(e.target.value)} />
            <button type="button" className="link" onClick={() => setEnd(currentTime().toFixed(2))}>Use current time</button>
          </label>
        </div>
        <label>
          Participant
          <select value={person} onChange={(e) => setPerson(e.target.value)}>
            <option value="">Whole scene (no participant)</option>
            {participantIds.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <label>Note (optional)<textarea value={note} rows={2} onChange={(e) => setNote(e.target.value)} /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="button-row">
          <button type="submit" className="primary" disabled={busy || !labelId}>Save annotation</button>
          <button type="button" disabled={busy} onClick={onClose}>Cancel</button>
        </div>
      </form>
    </aside>
  )
}
