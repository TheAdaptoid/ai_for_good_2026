import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, exportUrl, REVIEW_STATUSES, type VideoSummary } from '../api/client'
import { LatestImport, ReviewQueue } from '../components/ReviewQueue'
import { Empty, ErrorState, Loading } from '../components/States'
import { formatTime } from '../format'
import { useResource } from '../hooks'

const STATUS_LABELS: Record<string, string> = {
  UNREVIEWED: 'Unreviewed', ACCEPTED: 'Accepted', EDITED: 'Edited', DEFERRED: 'Deferred', REJECTED: 'Rejected',
}

function sum(videos: VideoSummary[], pick: (v: VideoSummary) => number): number {
  return videos.reduce((total, video) => total + pick(video), 0)
}

export function Dashboard() {
  const videos = useResource(api.videos, [])
  const participants = useResource(api.participants, [])

  if (videos.error) return <ErrorState error={videos.error} onRetry={videos.reload} />
  if (!videos.data) return <Loading what="videos" />
  const list = videos.data
  const annotationTotal = sum(list, (v) => Object.values(v.annotation_counts).reduce((a, b) => a + b, 0))
  const clipTotal = sum(list, (v) => v.clip_count)

  return (
    <>
      <div className="page-head">
        <h1>Dashboard</h1>
        <details className="menu">
          <summary>Export</summary>
          <ul>
            <li><a href={exportUrl('annotations', 'csv')} download>Annotations (CSV)</a></li>
            <li><a href={exportUrl('annotations', 'json')} download>Annotations (JSON)</a></li>
            <li><a href={exportUrl('history', 'csv')} download>Review history (CSV)</a></li>
            <li><a href={exportUrl('history', 'json')} download>Review history (JSON)</a></li>
          </ul>
        </details>
      </div>

      <section className="stats" aria-label="Totals">
        <Stat label="Videos" value={String(list.length)} />
        <Stat label="Footage" value={formatTime(sum(list, (v) => v.duration_seconds ?? 0))} />
        <Stat label="Anonymous participants"
          value={participants.data ? String(participants.data.length) : '…'}
          link={<Link to="/participants">Browse participants</Link>} />
        <Stat label="Review clips" value={String(clipTotal)} />
        <Stat label="Annotations" value={String(annotationTotal)} />
      </section>

      <LatestImport />
      {annotationTotal === 0 && clipTotal === 0 && (
        <p className="notice">
          No review clips or suggested annotations yet. They appear here once the clip and
          annotation pipeline has run. Until then you can watch videos, see who is on screen, and
          add annotations by hand.
        </p>
      )}

      <ReviewQueue videos={list} />

      <h2 className="section-title">Videos</h2>
      {list.length === 0 ? (
        <Empty>No processed videos in the database.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="videos">
            <thead>
              <tr>
                <th scope="col">Video</th>
                <th scope="col" className="num">Length</th>
                <th scope="col" className="num">Participants</th>
                <th scope="col" className="num">Review clips</th>
                {REVIEW_STATUSES.map((status) => (
                  <th scope="col" className="num" key={status}>{STATUS_LABELS[status]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((video) => (
                <tr key={video.video_id}>
                  <th scope="row"><Link to={`/videos/${video.video_id}`}>{video.title}</Link></th>
                  <td className="num">{formatTime(video.duration_seconds)}</td>
                  <td className="num">{video.participant_count}</td>
                  <td className="num">{video.clip_count}</td>
                  {REVIEW_STATUSES.map((status) => (
                    <td className={`num ${video.annotation_counts[status] ? '' : 'zero'}`} key={status}>
                      {video.annotation_counts[status] ?? 0}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function Stat({ label, value, link }: { label: string; value: string; link?: ReactNode }) {
  return (
    <div className="stat">
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
      {link}
    </div>
  )
}
