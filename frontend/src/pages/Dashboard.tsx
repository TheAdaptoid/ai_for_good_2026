import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CLIP_REVIEW_STATUSES, type VideoSummary } from '../api/client'
import { ActivityPie } from '../components/ActivityPie'
import { Icon, type IconName } from '../components/Icon'
import { Empty, ErrorState, Loading } from '../components/States'
import { formatTime } from '../format'
import { useIntro, useResource } from '../hooks'

const STATUS_LABELS: Record<string, string> = {
  UNREVIEWED: 'Unreviewed', ACCEPTED: 'Accepted', EDITED: 'Edited', DEFERRED: 'Deferred', REJECTED: 'Rejected',
}

// Clips with a staff decision; Deferred is postponed, not decided.
const reviewed = (v: VideoSummary) => (v.clip_status_counts?.ACCEPTED ?? 0) + (v.clip_status_counts?.EDITED ?? 0)

type Column = { key: string; label: string; value: (v: VideoSummary) => number }

const COLUMNS: Column[] = [
  { key: 'length', label: 'Length', value: (v) => v.duration_seconds ?? 0 },
  { key: 'participants', label: 'Participants', value: (v) => v.participant_count },
  { key: 'clips', label: 'Clips', value: (v) => v.person_clip_count ?? 0 },
  { key: 'reviewed', label: 'Reviewed Clips', value: reviewed },
  // Review status columns count stored clips, the records staff review on the Review page.
  ...CLIP_REVIEW_STATUSES.map((status) => ({ key: status, label: STATUS_LABELS[status], value: (v: VideoSummary) => v.clip_status_counts?.[status] ?? 0 })),
]

function sum(videos: VideoSummary[], pick: (v: VideoSummary) => number): number {
  return videos.reduce((total, video) => total + pick(video), 0)
}

export function Dashboard() {
  const videos = useResource(api.videos, [])
  const participants = useResource(api.participants, [])
  const [sort, setSort] = useState<{ key: string; dir: 'desc' | 'asc' } | null>(null)

  if (videos.error) return <ErrorState error={videos.error} onRetry={videos.reload} />
  if (!videos.data) return <Loading what="videos" />
  const list = videos.data
  const sortColumn = COLUMNS.find((c) => c.key === sort?.key)
  const rows = sortColumn ? [...list].sort((a, b) =>
    (sort!.dir === 'desc' ? sortColumn.value(b) - sortColumn.value(a) : sortColumn.value(a) - sortColumn.value(b))
    || a.video_id - b.video_id) : list
  const toggleSort = (key: string) =>
    setSort(sort?.key === key && sort.dir === 'desc' ? { key, dir: 'asc' } : { key, dir: 'desc' })
  const annotationTotal = sum(list, (v) => Object.values(v.annotation_counts).reduce((a, b) => a + b, 0))
  const clipTotal = sum(list, (v) => v.clip_count)
  const storedClipTotal = sum(list, (v) => v.person_clip_count ?? 0)
  const humanTotal = sum(list, (v) => v.human_annotation_count ?? 0)

  return (
    <>
      <p className="site-title">The Performance Academy Video Intelligence</p>
      <div className="page-head">
        <h1>Dashboard</h1>
      </div>
      <hr className="divider" />

      <section className="stats" aria-label="Totals">
        <Stat icon="video" tone="purple" label="Videos" count={list.length} hint="Processed videos in the database." />
        <Stat icon="clock" tone="blue" label="Footage" count={sum(list, (v) => v.duration_seconds ?? 0)} format={formatTime}
          hint="Total running time of all videos." />
        <Stat icon="participants" tone="magenta" label="Participants" count={participants.data?.length ?? null}
          hint="Anonymous people detected across all videos." />
        <Stat icon="clips" tone="orange" label="Clips" count={storedClipTotal}
          hint="Segments where the same people stay on screen, reviewed on the Review page." />
        <Stat icon="pen" tone="green" label="Human Annotations" count={humanTotal}
          hint="Records created or corrected by staff. Each counts once." />
      </section>

      {annotationTotal === 0 && clipTotal === 0 && storedClipTotal === 0 && (
        <p className="notice">
          No review clips or suggested annotations yet. They appear here once the clip and
          annotation pipeline has run. Until then you can watch videos, see who is on screen, and
          add annotations by hand.
        </p>
      )}

      <ActivityPie />

      <section className="queue gray-panel videos-panel" aria-labelledby="videos-title">
      <h2 id="videos-title">Videos</h2>
      {list.length === 0 ? (
        <Empty>No processed videos in the database.</Empty>
      ) : (
        <div className="table-wrap" role="region" aria-label="Videos" tabIndex={0}>
          <table className="videos">
            <thead>
              <tr>
                <th scope="col">Video</th>
                {COLUMNS.map((column) => {
                  const active = sort?.key === column.key
                  return (
                    <th scope="col" className="num" key={column.key}
                      aria-sort={active ? (sort.dir === 'desc' ? 'descending' : 'ascending') : 'none'}>
                      <button type="button" className="sort-button" onClick={() => toggleSort(column.key)}
                        title={active && sort.dir === 'desc' ? 'Sort low to high' : 'Sort high to low'}>
                        {column.label}<span aria-hidden="true" className="sort-button__arrow">{active ? (sort.dir === 'desc' ? '↓' : '↑') : '↕'}</span>
                      </button>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((video) => (
                <tr key={video.video_id}>
                  <th scope="row"><Link to={`/videos/${video.video_id}`}>{video.title}</Link></th>
                  <td className="num">{formatTime(video.duration_seconds)}</td>
                  <td className="num">{video.participant_count}</td>
                  <td className="num">{video.person_clip_count ?? 0}</td>
                  <td className="num">{reviewed(video)}</td>
                  {CLIP_REVIEW_STATUSES.map((status) => (
                    <td className={`num ${video.clip_status_counts?.[status] ? '' : 'zero'}`} key={status}>
                      {video.clip_status_counts?.[status] ?? 0}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      </section>
    </>
  )
}

const whole = (n: number) => String(Math.round(n))

function Stat({ icon, tone, label, count, format = whole, hint }: {
  icon: IconName; tone: 'purple' | 'blue' | 'magenta' | 'orange' | 'green'; label: string
  count: number | null; format?: (n: number) => string; hint: string
}) {
  const id = useId()
  const t = useIntro(count !== null) // counts up from 0 on load; screen readers get only the final value
  return (
    <div className={`stat stat--${tone}`}>
      <span className="stat__icon"><Icon name={icon} /></span>
      <span className="stat__value">
        {count === null ? '…' : <>
          <span aria-hidden="true">{format(count * t)}</span>
          <span className="sr-only">{format(count)}</span>
        </>}
      </span>
      <span className="stat__label">{label}</span>
      {/* Shown on icon hover or focus; Escape dismisses it (WCAG 1.4.13). */}
      <span className="stat__info" tabIndex={0} aria-label={`About ${label}`} aria-describedby={id}
        onKeyDown={(e) => { if (e.key === 'Escape') e.currentTarget.blur() }}>i</span>
      <span className="stat__tip" role="tooltip" id={id}>{hint}</span>
    </div>
  )
}
