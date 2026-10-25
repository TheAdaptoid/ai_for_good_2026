import { Link } from 'react-router-dom'
import { api, type ImportRun, type VideoSummary } from '../api/client'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { Empty, ErrorState, Loading } from './States'

/** Clips across all videos, highest review priority first. Priority is a ranking, not a percentage. */
export function ReviewQueue({ videos }: { videos: VideoSummary[] }) {
  const clips = useResource(() => api.clips({ order: 'priority', limit: 10 }), [])
  const titles = new Map(videos.map((v) => [v.video_id, v.title]))

  return (
    <section className="queue" aria-labelledby="queue-title">
      <h2 id="queue-title">Review queue</h2>
      <p className="muted small">
        Review clips ordered by review priority, a ranking heuristic that suggests what to look at
        first. It is not a probability or a confidence.
      </p>
      {clips.error && <ErrorState error={clips.error} onRetry={clips.reload} />}
      {!clips.data && !clips.error && <Loading what="review clips" />}
      {clips.data && clips.data.length === 0 && (
        <Empty>No review clips have been imported yet.</Empty>
      )}
      {clips.data && clips.data.length > 0 && (
        <ol className="queue__list">
          {clips.data.map((clip) => (
            <li key={clip.clip_id}>
              <Link to={`/videos/${clip.video_id}?t=${(clip.start_seconds ?? 0).toFixed(2)}&clip=${clip.clip_id}`}>
                {titles.get(clip.video_id) ?? `Video ${clip.video_id}`} · {formatTime(clip.start_seconds)}–{formatTime(clip.end_seconds)}
              </Link>
              <span className="muted">
                {' '}{clip.person_ids.length} participant{clip.person_ids.length === 1 ? '' : 's'} ·{' '}
                {clip.priority_score === null ? 'review priority not computed' : `review priority ${clip.priority_score.toFixed(2)}`}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export function LatestImport() {
  const runs = useResource(api.imports, [])
  if (runs.error) return <ErrorState error={runs.error} onRetry={runs.reload} />
  if (!runs.data) return null
  const latest: ImportRun | undefined = runs.data[0]
  return (
    <p className="muted small import-line">
      {latest
        ? <>Latest pipeline import: <strong>{latest.pipeline_name} {latest.pipeline_version}</strong> on{' '}
            {new Date(latest.imported_at).toLocaleString()} ({latest.counts.inserted} annotations and{' '}
            {latest.counts.clips_inserted} clips added, {latest.counts.skipped_protected} reviewed annotations left untouched)</>
        : 'No pipeline output has been imported yet.'}
    </p>
  )
}
