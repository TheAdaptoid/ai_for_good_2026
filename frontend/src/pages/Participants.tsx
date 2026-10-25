import { useState } from 'react'
import { Link, NavLink, useParams } from 'react-router-dom'
import { api, ApiError, type Annotation, type ParticipantVideo, type PresenceInterval, type ReviewClip } from '../api/client'
import { StatusBadges } from '../components/StatusBadge'
import { Empty, ErrorState, Loading } from '../components/States'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { NotFound } from './NotFound'

export function Participants() {
  const personId = useParams().personId
  const list = useResource(api.participants, [])
  const [filter, setFilter] = useState('')
  const shown = (list.data ?? []).filter((p) => p.person_id.toLowerCase().includes(filter.trim().toLowerCase()))

  return (
    <div className="participants-page">
      <aside className="people-list" aria-label="Participants">
        <h1>Participants</h1>
        <label>
          Find an anonymous ID
          <input type="search" value={filter} placeholder="e.g. 0001" onChange={(e) => setFilter(e.target.value)} />
        </label>
        {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
        {!list.data && !list.error && <Loading what="participants" />}
        {list.data && shown.length === 0 && <Empty>No participant matches “{filter}”.</Empty>}
        <ul>
          {shown.map((p) => (
            <li key={p.person_id}>
              <NavLink to={`/participants/${encodeURIComponent(p.person_id)}`}>
                <span>{p.person_id}</span>
                <span className="muted small">{p.video_count} videos</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </aside>
      <section className="person-detail">
        {personId ? <ParticipantDetail key={personId} personId={personId} />
          : <Empty>Choose a participant to see every video and moment they appear in.</Empty>}
      </section>
    </div>
  )
}

type ParticipantVideoRow = ParticipantVideo & { duration: number; intervals: readonly PresenceInterval[] }

function ParticipantDetail({ personId }: { personId: string }) {
  const detail = useResource(async () => {
    const found = await api.participant(personId)
    // Presence comes from the same per-video endpoint the video view uses.
    const videos: ParticipantVideoRow[] = await Promise.all(found.videos.map(async (v) => {
      const [summary, people] = await Promise.all([api.video(v.video_id), api.videoParticipants(v.video_id)])
      return { ...v, duration: summary.duration_seconds ?? v.last_seconds,
        intervals: people.find((p) => p.person_id === personId)?.intervals ?? [] }
    }))
    return videos
  }, [personId])
  const annotations = useResource(() => api.annotations({ person_id: personId }), [personId])
  const clips = useResource(() => api.clips({ person_id: personId }), [personId])

  if (detail.error instanceof ApiError && detail.error.status === 404) return <NotFound what="participant" />
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />
  if (!detail.data) return <Loading what={personId} />
  const byVideo = new Map<number, Annotation[]>()
  for (const a of annotations.data ?? []) byVideo.set(a.video_id, [...(byVideo.get(a.video_id) ?? []), a])
  const clipsByVideo = new Map<number, ReviewClip[]>()
  for (const c of clips.data ?? []) clipsByVideo.set(c.video_id, [...(clipsByVideo.get(c.video_id) ?? []), c])

  return (
    <>
      <h2>{personId}</h2>
      <p className="muted">
        Anonymous ID. Appears in {detail.data.length} video{detail.data.length === 1 ? '' : 's'}
        {annotations.data && ` · ${annotations.data.length} current annotations`}.
      </p>
      {annotations.error && <ErrorState error={annotations.error} onRetry={annotations.reload} />}
      {clips.error && <ErrorState error={clips.error} onRetry={clips.reload} />}
      {detail.data.length === 0 && <Empty>This participant does not appear in any processed video.</Empty>}
      {detail.data.map((v) => (
        <article className="appearance" key={v.video_id}>
          <header>
            <h3><Link to={`/videos/${v.video_id}?t=${v.first_seconds.toFixed(2)}`}>{v.title}</Link></h3>
            <span className="muted small">
              {formatTime(v.first_seconds)} – {formatTime(v.last_seconds)} · {v.detection_count} detections
            </span>
          </header>
          <div className="mini-track" aria-label={`${personId} presence in ${v.title}`}>
            {v.intervals.map((i) => (
              <Link key={i.start_seconds} className="bar bar--presence"
                to={`/videos/${v.video_id}?t=${i.start_seconds.toFixed(2)}`}
                style={{ left: `${(i.start_seconds / v.duration) * 100}%`,
                  width: `max(3px, ${((i.end_seconds - i.start_seconds) / v.duration) * 100}%)` }}
                title={`On screen ${formatTime(i.start_seconds)}–${formatTime(i.end_seconds)}`}
                aria-label={`On screen at ${formatTime(i.start_seconds)}`} />
            ))}
          </div>
          {(clipsByVideo.get(v.video_id) ?? []).length > 0 && (
            <p className="clip-chips">
              <span className="muted small">Review clips: </span>
              {(clipsByVideo.get(v.video_id) ?? []).map((c) => (
                <Link key={c.clip_id} className="chip"
                  to={`/videos/${v.video_id}?t=${(c.start_seconds ?? 0).toFixed(2)}&clip=${c.clip_id}`}
                  title={c.priority_score === null ? 'Review priority not computed' : `Review priority ${c.priority_score.toFixed(2)}`}>
                  {formatTime(c.start_seconds)}–{formatTime(c.end_seconds)}
                </Link>
              ))}
            </p>
          )}
          {(byVideo.get(v.video_id) ?? []).length > 0 && (
            <ul className="moment-list">
              {(byVideo.get(v.video_id) ?? []).map((a) => (
                <li key={a.annotation_id}>
                  <Link to={`/videos/${v.video_id}?t=${(a.start_seconds ?? 0).toFixed(2)}&annotation=${a.annotation_id}`}>
                    {formatTime(a.start_seconds)}–{formatTime(a.end_seconds)} {a.label_name}
                  </Link>
                  <span className="muted small"> {a.label_category}</span>
                  <StatusBadges annotation={a} />
                </li>
              ))}
            </ul>
          )}
        </article>
      ))}
    </>
  )
}
