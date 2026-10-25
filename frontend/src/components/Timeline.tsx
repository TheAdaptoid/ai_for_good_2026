import { memo, useMemo, type CSSProperties, type MouseEvent } from 'react'
import { Link } from 'react-router-dom'
import type { Annotation, PersonClip, PresenceInterval, ReviewClip, VideoParticipant } from '../api/client'
import { formatTime, tickStep } from '../format'

interface Props {
  duration: number
  storedClips?: PersonClip[]
  selectedStoredClipId?: number | null
  onSelectStoredClip?: (clip: PersonClip) => void
  clips: ReviewClip[]
  annotations: Annotation[]
  participants: VideoParticipant[]
  currentTime: number
  selectedId: number | null
  selectedClipId: number | null
  onSeek: (seconds: number) => void
  onSelect: (annotation: Annotation) => void
  onSelectClip: (clip: ReviewClip) => void
}

const pct = (seconds: number, duration: number) => `${(Math.min(Math.max(seconds, 0), duration) / duration) * 100}%`

function spanStyle(start: number, end: number, duration: number) {
  return { left: pct(start, duration), width: `max(3px, ${((end - start) / duration) * 100}%)` }
}

/** Seek to the clicked position on an empty part of a track. */
function seekFromTrack(event: MouseEvent<HTMLDivElement>, duration: number, onSeek: (t: number) => void) {
  if (event.target !== event.currentTarget) return
  const rect = event.currentTarget.getBoundingClientRect()
  onSeek(((event.clientX - rect.left) / rect.width) * duration)
}

function annotationClass(annotation: Annotation, selected: boolean): string {
  return [
    'bar', 'bar--annotation', `bar--${annotation.label_category}`,
    annotation.source === 'AI' && annotation.review_status === 'UNREVIEWED' ? 'bar--suggestion' : 'bar--reviewed',
    `bar--${annotation.review_status.toLowerCase()}`,
    selected ? 'bar--selected' : '',
  ].join(' ')
}

function annotationTitle(a: Annotation): string {
  const confidence = a.confidence === null ? '' : `, model confidence ${a.confidence.toFixed(2)}`
  return `${a.label_name} (${a.label_category}) ${formatTime(a.start_seconds)}–${formatTime(a.end_seconds)}, ${a.source}, ${a.review_status}${confidence}`
}

const NONE: Annotation[] = []

function group(annotations: Annotation[], participants: VideoParticipant[]) {
  const byPerson = new Map<string, Annotation[]>()
  const scene: Annotation[] = []
  for (const annotation of annotations) {
    if (annotation.person_id === null) scene.push(annotation)
    else byPerson.set(annotation.person_id, [...(byPerson.get(annotation.person_id) ?? []), annotation])
  }
  // Annotated participants without detections in this video still get a row.
  const people: { person_id: string; intervals: readonly PresenceInterval[] }[] = [...participants]
  for (const personId of byPerson.keys()) {
    if (!participants.some((p) => p.person_id === personId)) people.push({ person_id: personId, intervals: [] })
  }
  return { byPerson, scene, people }
}

export function Timeline({ duration, storedClips = [], selectedStoredClipId, onSelectStoredClip, clips, annotations, participants, currentTime, selectedId, selectedClipId, onSeek, onSelect, onSelectClip }: Props) {
  const { byPerson, scene, people } = useMemo(() => group(annotations, participants), [annotations, participants])
  const step = tickStep(duration)
  const ticks = Array.from({ length: Math.floor(duration / step) + 1 }, (_, i) => i * step)

  return (
    <div className="timeline-scroll" role="region" aria-label="Scrollable video timeline" tabIndex={0}>
      <div className="timeline" aria-label="Video timeline">
        <div className="timeline__content">
          <div className="timeline__playhead" style={{ '--at': Math.min(1, Math.max(0, currentTime / duration)) } as CSSProperties} aria-hidden />
          <div className="row row--axis">
            <div className="row__label">{formatTime(currentTime)}</div>
            <div className="row__track" onClick={(e) => seekFromTrack(e, duration, onSeek)}>
              {ticks.map((t) => (
                <span key={t} className="tick" style={{ left: pct(t, duration) }}>{formatTime(t)}</span>
              ))}
            </div>
          </div>
          {storedClips.length > 0 && <div className="row">
            <div className="row__label">Clips</div>
            <div className="row__track" onClick={(event) => seekFromTrack(event, duration, onSeek)}>
              {storedClips.map((clip) => <button key={clip.clip_id} type="button"
                className={`bar bar--clip ${clip.clip_id === selectedStoredClipId ? 'bar--selected' : ''}`}
                style={spanStyle(clip.start_seconds, clip.end_seconds, duration)}
                aria-current={currentTime >= clip.start_seconds && currentTime < clip.end_seconds ? 'time' : undefined}
                aria-label={`Clip #${clip.clip_id} at ${formatTime(clip.start_seconds)}`}
                title={`Clip #${clip.clip_id}: ${formatTime(clip.start_seconds)}–${formatTime(clip.end_seconds)}, ${clip.person_ids.length} participants`}
                onClick={() => { onSeek(clip.start_seconds); onSelectStoredClip?.(clip) }} />)}
            </div>
          </div>}
          <div className="row">
            <div className="row__label">Review clips</div>
            <div className="row__track" onClick={(e) => seekFromTrack(e, duration, onSeek)}>
              {clips.length === 0 && <span className="row__empty">none yet</span>}
              {clips.map((clip) => (
                <button key={clip.clip_id} type="button" className={`bar bar--clip ${clip.clip_id === selectedClipId ? 'bar--selected' : ''}`}
                  aria-current={currentTime >= (clip.start_seconds ?? 0) && currentTime <= (clip.end_seconds ?? 0) ? 'time' : undefined}
                  style={spanStyle(clip.start_seconds ?? 0, clip.end_seconds ?? 0, duration)}
                  title={`Review clip ${formatTime(clip.start_seconds)}–${formatTime(clip.end_seconds)}, ${clip.person_ids.length} participants${clip.priority_score === null ? ', review priority not computed' : `, review priority ${clip.priority_score.toFixed(2)}`}`}
                  aria-label={`Review clip at ${formatTime(clip.start_seconds)}`}
                  onClick={() => {
                    onSeek(clip.start_seconds ?? 0)
                    onSelectClip(clip)
                  }}>
                  {clip.priority_score === null ? '' : clip.priority_score.toFixed(2)}
                </button>
              ))}
            </div>
          </div>
          <AnnotationRow label="Scene" annotations={scene} duration={duration} selectedId={selectedId}
            onSeek={onSeek} onSelect={onSelect} />
          <div className="timeline__people">
            {people.map((person) => (
              <PersonRow key={person.person_id} personId={person.person_id} intervals={person.intervals}
                currentIntervalIndex={person.intervals.findIndex((interval) => currentTime >= interval.start_seconds && currentTime <= interval.end_seconds)}
                annotations={byPerson.get(person.person_id) ?? NONE} duration={duration}
                selectedId={selectedId} onSeek={onSeek} onSelect={onSelect} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

interface RowProps {
  duration: number
  annotations: Annotation[]
  selectedId: number | null
  onSeek: (seconds: number) => void
  onSelect: (annotation: Annotation) => void
}

function AnnotationBars({ annotations, duration, selectedId, onSeek, onSelect }: RowProps) {
  return annotations.map((a) => (
    <button key={a.annotation_id} type="button" className={annotationClass(a, a.annotation_id === selectedId)}
      style={spanStyle(a.start_seconds ?? 0, a.end_seconds ?? 0, duration)} title={annotationTitle(a)}
      aria-label={annotationTitle(a)}
      onClick={() => {
        onSeek(a.start_seconds ?? 0)
        onSelect(a)
      }}>
      <span className="bar__text">{a.label_name}</span>
    </button>
  ))
}

function AnnotationRow({ label, ...props }: RowProps & { label: string }) {
  return (
    <div className="row">
      <div className="row__label">{label}</div>
      <div className="row__track" onClick={(e) => seekFromTrack(e, props.duration, props.onSeek)}>
        <AnnotationBars {...props} />
      </div>
    </div>
  )
}

// Memoized so playhead updates do not re-render hundreds of presence bars.
const PersonRow = memo(function PersonRow(
  { personId, intervals, currentIntervalIndex, ...props }: RowProps & { personId: string; intervals: readonly PresenceInterval[]; currentIntervalIndex: number },
) {
  return (
    <div className="row">
      <div className="row__label">
        <Link to={`/participants/${encodeURIComponent(personId)}`}>{personId}</Link>
      </div>
      <div className="row__track" onClick={(e) => seekFromTrack(e, props.duration, props.onSeek)}>
        {intervals.map((interval, index) => (
          <button key={interval.start_seconds} type="button" className="bar bar--presence"
            aria-current={index === currentIntervalIndex ? 'time' : undefined}
            style={spanStyle(interval.start_seconds, interval.end_seconds, props.duration)}
            title={`${personId} on screen ${formatTime(interval.start_seconds)}–${formatTime(interval.end_seconds)}`}
            aria-label={`${personId} on screen ${formatTime(interval.start_seconds)}–${formatTime(interval.end_seconds)}`}
            onClick={() => props.onSeek(interval.start_seconds)} />
        ))}
        <AnnotationBars {...props} />
      </div>
    </div>
  )
})
