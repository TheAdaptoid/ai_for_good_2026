import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type VideoSummary } from '../api/client'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { Empty, ErrorState, Loading } from './States'

export function DatabaseClips({ videos }: { videos: VideoSummary[] }) {
  const [offset, setOffset] = useState(0)
  const clips = useResource(() => api.personClips({ limit: 10, offset }), [offset])
  const total = videos.reduce((sum, video) => sum + (video.person_clip_count ?? 0), 0)
  return (
    <section className="queue" aria-label="Database clips">
      <h2>Clips</h2>
      <p className="muted">Stored person-presence clips, ordered by video and time. Review priority has not been computed for these clips.</p>
      {clips.error && <ErrorState error={clips.error} onRetry={clips.reload} />}
      {clips.loading && <Loading what="clips" />}
      {!clips.loading && clips.data?.length === 0 && <Empty>No person-presence clips in the database.</Empty>}
      {!clips.loading && clips.data && clips.data.length > 0 && <>
        <ol className="queue__list" start={offset + 1}>{clips.data.map((clip) => <li key={clip.clip_id}>
          <Link to={`/videos/${clip.video_id}?t=${clip.start_seconds}&person_clip=${clip.clip_id}`}>
            {videos.find((video) => video.video_id === clip.video_id)?.title ?? `Video ${clip.video_id}`} · {formatTime(clip.start_seconds)}–{formatTime(clip.end_seconds)}
          </Link><span className="muted">{clip.person_ids.length} participants</span>
        </li>)}</ol>
        <p className="small">Showing {offset + 1}–{offset + clips.data.length} of {total}</p>
      </>}
      {total > 10 && <div className="button-row">
        <button disabled={offset === 0 || clips.loading} onClick={() => setOffset(offset - 10)}>Previous clips</button>
        <button disabled={offset + 10 >= total || clips.loading} onClick={() => setOffset(offset + 10)}>Next clips</button>
      </div>}
    </section>
  )
}
