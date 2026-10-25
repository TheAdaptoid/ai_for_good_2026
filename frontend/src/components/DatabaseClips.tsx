import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CLIP_REVIEW_STATUSES, type ClipReviewStatus, type VideoSummary } from '../api/client'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { Icon } from './Icon'
import { Empty, ErrorState, Loading } from './States'

const PAGE = 10 // two rows of five on wide screens

export function DatabaseClips({ videos }: { videos: VideoSummary[] }) {
  const [offset, setOffset] = useState(0)
  const [status, setStatus] = useState<ClipReviewStatus | null>(null)
  const counts = useResource(api.personClipStatusCounts, [])
  const clips = useResource(() => api.personClips({ review_status: status ?? undefined, limit: PAGE, offset }), [offset, status])
  const all = counts.data
    ? CLIP_REVIEW_STATUSES.reduce((sum, key) => sum + counts.data![key], 0)
    : videos.reduce((sum, video) => sum + (video.person_clip_count ?? 0), 0)
  const total = status && counts.data ? counts.data[status] : all
  const tabs: [ClipReviewStatus | null, string][] = [[null, 'All'], ...CLIP_REVIEW_STATUSES.map(
    (key): [ClipReviewStatus, string] => [key, key[0] + key.slice(1).toLowerCase()])]
  return (
    <section className="queue clip-browser" aria-label="Database clips">
      <h2>Clips</h2>
      <p className="muted">Choose a clip to watch its excerpt and inspect its activity and engagement values.</p>
      <div className="status-tabs" role="group" aria-label="Filter by review status">
        {tabs.map(([key, label]) => (
          <button key={label} type="button" aria-pressed={status === key}
            onClick={() => { setStatus(key); setOffset(0) }}>
            {label}{counts.data && <>{' '}<span className="status-tabs__count">{key ? counts.data[key] : all}</span></>}
          </button>
        ))}
      </div>
      {/* The selected tab and this panel share one fill, so they read as an open folder. */}
      <div className="folder">
      {clips.error && <ErrorState error={clips.error} onRetry={clips.reload} />}
      {clips.loading && <Loading what="clips" />}
      {!clips.loading && clips.data?.length === 0 && <Empty>{status ? `No ${status.toLowerCase()} clips.` : 'No person-presence clips in the database.'}</Empty>}
      {!clips.loading && clips.data && clips.data.length > 0 && <>
        <ol className="clip-grid" start={offset + 1}>{clips.data.map((clip) => <li key={clip.clip_id}>
          <Link className="clip-tile" to={`/review/clips/${clip.clip_id}`}>
            {/* A small JPEG decoded on request; video elements here held the browser's few connections. */}
            <img className="clip-tile__thumb" src={`/api/person-clips/${clip.clip_id}/thumbnail`} alt=""
              loading="lazy" decoding="async" onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
            <span className="clip-tile__title">{videos.find((video) => video.video_id === clip.video_id)?.title ?? `Video ${clip.video_id}`}</span>
            <span className="muted small">{formatTime(clip.start_seconds)}–{formatTime(clip.end_seconds)} · <span className="clip-tile__people">{clip.person_ids.length} participant{clip.person_ids.length === 1 ? '' : 's'}</span></span>
          </Link>
        </li>)}</ol>
        <p className="small">Showing {offset + 1}–{offset + clips.data.length} of {total}</p>
      </>}
      {total > PAGE && (() => {
        const lastOffset = Math.floor((total - 1) / PAGE) * PAGE
        const atStart = offset === 0 || clips.loading
        const atEnd = offset >= lastOffset || clips.loading
        return (
          <nav className="pager" aria-label="Clip pages">
            <button type="button" className="pager__button" aria-label="First page" disabled={atStart} onClick={() => setOffset(0)}><Icon name="first" /></button>
            <button type="button" className="pager__button" aria-label="Previous page" disabled={atStart} onClick={() => setOffset(offset - PAGE)}><Icon name="previous" /></button>
            <span className="pager__status" aria-live="polite">Page {offset / PAGE + 1} of {lastOffset / PAGE + 1}</span>
            <button type="button" className="pager__button" aria-label="Next page" disabled={atEnd} onClick={() => setOffset(offset + PAGE)}><Icon name="next" /></button>
            <button type="button" className="pager__button" aria-label="Last page" disabled={atEnd} onClick={() => setOffset(lastOffset)}><Icon name="last" /></button>
          </nav>
        )
      })()}
      </div>
    </section>
  )
}
