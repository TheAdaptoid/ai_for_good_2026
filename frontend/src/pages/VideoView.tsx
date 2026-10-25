import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, streamUrl, type Annotation, type PersonClip, type ReviewClip } from '../api/client'
import { StoredClipPanel } from '../components/StoredClipPanel'
import { ClipPanel } from '../components/ClipPanel'
import { CreateForm } from '../components/CreateForm'
import { ReviewPanel } from '../components/ReviewPanel'
import { Empty, ErrorState, Loading } from '../components/States'
import { Timeline } from '../components/Timeline'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { NotFound } from './NotFound'

export function VideoView() {
  const navigate = useNavigate()
  const videoId = Number(useParams().videoId)
  const [params, setParams] = useSearchParams()
  const startAt = Number(params.get('t') ?? 0)
  const selectedId = params.get('annotation') ? Number(params.get('annotation')) : null
  const storedClipId = params.get('person_clip') ? Number(params.get('person_clip')) : null
  const clipId = params.get('clip') ? Number(params.get('clip')) : null
  const [clipFilter, setClipFilter] = useState<'all' | 'impact'>('all')
  const [showRejected, setShowRejected] = useState(false)
  const [creating, setCreating] = useState(false)
  const [currentTime, setCurrentTime] = useState(startAt)
  const [fileMissing, setFileMissing] = useState(false)
  const player = useRef<HTMLVideoElement>(null)

  const video = useResource(() => api.video(videoId), [videoId])
  const participants = useResource(() => api.videoParticipants(videoId), [videoId])
  const annotations = useResource(() => api.annotations({ video_id: videoId, include_rejected: showRejected }),
    [videoId, showRejected])
  const clips = useResource(() => api.clips({ video_id: videoId }), [videoId])
  const storedClips = useResource(() => api.personClips({ video_id: videoId }), [videoId])
  const videoClips = useMemo(() => storedClips.data?.filter((clip) => clip.video_id === videoId), [storedClips.data, videoId])
  const highImpactClips = useMemo(() => (videoClips ?? [])
    .filter((clip) => typeof clip.impact_score === 'number')
    .sort((a, b) => b.impact_score! - a.impact_score! || a.start_seconds - b.start_seconds || a.clip_id - b.clip_id)
    .slice(0, 10), [videoClips])
  const visibleStoredClips = clipFilter === 'impact' ? highImpactClips : videoClips
  const storedClip = useResource(() => storedClipId === null ? Promise.resolve(null) : api.personClip(storedClipId), [storedClipId])
  const labels = useResource(api.labels, [])
  // Loaded on its own so a just-rejected (hidden) annotation stays open in the panel.
  const selected = useResource(() => selectedId === null ? Promise.resolve(null) : api.annotation(selectedId),
    [selectedId, annotations.data])

  const selectedClip = useResource(() => clipId === null ? Promise.resolve(null) : api.clip(clipId), [clipId])

  const seek = useCallback((seconds: number) => {
    if (player.current) player.current.currentTime = seconds
    setCurrentTime(seconds)
  }, [])
  const select = useCallback((annotation: Annotation) => {
    setCreating(false)
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('annotation', String(annotation.annotation_id))
      next.delete('person_clip')
      return next
    }, { replace: true })
  }, [setParams])
  const selectClip = useCallback((clip: ReviewClip) => {
    setCreating(false)
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('clip', String(clip.clip_id))
      next.delete('person_clip')
      next.delete('annotation')
      return next
    }, { replace: true })
  }, [setParams])
  const selectStoredClip = (clip: PersonClip) => {
    setCreating(false)
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('person_clip', String(clip.clip_id))
      next.set('t', String(clip.start_seconds))
      next.delete('clip')
      next.delete('annotation')
      return next
    }, { replace: true })
  }
  const closeStoredClip = () => setParams((current) => {
    const next = new URLSearchParams(current)
    next.delete('person_clip')
    return next
  }, { replace: true })
  const closeClip = () => setParams((current) => {
    const next = new URLSearchParams(current)
    next.delete('clip')
    return next
  }, { replace: true })
  const closePanel = () => setParams((current) => {
    const next = new URLSearchParams(current)
    next.delete('annotation')
    return next
  }, { replace: true })
  const participantIds = useMemo(() => (participants.data ?? []).map((p) => p.person_id), [participants.data])

  if (video.error instanceof ApiError && video.error.status === 404) return <NotFound what="video" />
  if (video.error) return <ErrorState error={video.error} onRetry={video.reload} />
  if (!video.data) return <Loading what="video" />
  const summary = video.data
  const fps = summary.fps ?? 0
  const duration = summary.duration_seconds ?? 0
  const changed = () => {
    annotations.reload()
    video.reload()
  }

  return (
    <div className="video-page">
      <div className="page-head">
        <div>
          <button type="button" className="back-button" onClick={() => void navigate('/')}>Back</button>
          <h1>{summary.title}</h1>
          <p className="muted">
            {formatTime(duration)} · {summary.participant_count} anonymous participants ·{' '}
            {summary.person_clip_count ?? 0} clips · {summary.clip_count} review clips
          </p>
        </div>
        <button type="button" className="primary" disabled={!fps || !labels.data}
          onClick={() => {
            // Clear both selections together: separate search-param updates do not compose.
            setParams((current) => {
              const next = new URLSearchParams(current)
              next.delete('annotation')
              next.delete('clip')
              next.delete('person_clip')
              return next
            }, { replace: true })
            setCreating(true)
          }}>
          Add annotation
        </button>
      </div>

      <div className="video-layout">
        <div className="video-main">
          {fileMissing ? (
            <div className="player player--missing" role="alert">The video file is unavailable on this machine.</div>
          ) : (
            <video ref={player} className="player" controls preload="metadata" src={streamUrl(videoId)}
              onLoadedMetadata={(e) => { if (startAt) e.currentTarget.currentTime = startAt }}
              onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
              onError={() => setFileMissing(true)} />
          )}

          <div className="timeline-tools">
            <label className="clip-filter">
              Clip filter
              <select value={clipFilter} onChange={(event) => {
                const next = event.target.value as 'all' | 'impact'
                setClipFilter(next)
                if (next === 'impact' && storedClipId !== null && !highImpactClips.some((clip) => clip.clip_id === storedClipId)) closeStoredClip()
              }}>
                <option value="all">All clips</option>
                <option value="impact">High impact: top 10</option>
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} />
              Show rejected annotations
            </label>
            <span className="legend">
              <span className="legend__item"><i className="swatch swatch--playback" /> current playback position</span>
              <span className="legend__item"><i className="swatch swatch--presence" /> on screen (face detections)</span>
              <span className="legend__item"><i className="swatch swatch--activity" /> activity</span>
              <span className="legend__item"><i className="swatch swatch--observation" /> observation</span>
              <span className="legend__item"><i className="swatch swatch--suggestion" /> unreviewed AI suggestion</span>
            </span>
          </div>

          {clipFilter === 'impact' && <section aria-label="High-impact clips">
            <h2 className="section-title">Top 10 high-impact clips</h2>
            <p className="muted small">Ranked for review by 1.1^N × mean positive score, where N is the number of people in the clip. This is a ranking suggestion, not model confidence. Clips without visible-affect observations are unscored.</p>
            {storedClips.loading && <Loading what="impact scores" />}
            {!storedClips.loading && !storedClips.error && highImpactClips.length === 0 && <Empty>No clips have visible-affect observations to score.</Empty>}
            {!storedClips.loading && highImpactClips.length > 0 && <ol className="impact-list">
              {highImpactClips.map((clip) => <li key={clip.clip_id}>
                <button type="button" className="link" onClick={() => { seek(clip.start_seconds); selectStoredClip(clip) }}>
                  Clip #{clip.clip_id}: {formatTime(clip.start_seconds)}–{formatTime(clip.end_seconds)}
                </button>
                <span>Impact score {clip.impact_score!.toFixed(3)} · {clip.person_ids.length} participant{clip.person_ids.length === 1 ? '' : 's'}</span>
              </li>)}
            </ol>}
          </section>}
          {participants.error && <ErrorState error={participants.error} onRetry={participants.reload} />}
          {annotations.error && <ErrorState error={annotations.error} onRetry={annotations.reload} />}
          {storedClips.error && <ErrorState error={storedClips.error} onRetry={storedClips.reload} />}
          {storedClip.error && <ErrorState error={storedClip.error} onRetry={storedClip.reload} />}
          {clips.error && <ErrorState error={clips.error} onRetry={clips.reload} />}
          {participants.data && annotations.data && clips.data && duration > 0 ? (
            <Timeline duration={duration} storedClips={visibleStoredClips} selectedStoredClipId={storedClipId} onSelectStoredClip={selectStoredClip} clips={clips.data} annotations={annotations.data}
              participants={participants.data} currentTime={currentTime} selectedId={selectedId}
              selectedClipId={clipId} onSeek={seek} onSelect={select} onSelectClip={selectClip} />
          ) : (
            !participants.error && !annotations.error && !clips.error && <Loading what="timeline" />
          )}
        </div>

        {storedClip.data && !selected.data && !creating && <StoredClipPanel clip={storedClip.data} onClose={closeStoredClip} />}
        {selected.data && labels.data && (
          <ReviewPanel key={selected.data.annotation_id} annotation={selected.data} labels={labels.data} fps={fps}
            participantIds={participantIds} onChanged={changed} onClose={closePanel} />
        )}
        {!selected.data && !creating && storedClipId === null && selectedClip.data && (
          <ClipPanel key={selectedClip.data.clip_id} clip={selectedClip.data} showRejected={showRejected}
            version={annotations.data} onSelect={select} onClose={closeClip} />
        )}
        {creating && labels.data && (
          <CreateForm videoId={videoId} fps={fps} labels={labels.data} participantIds={participantIds}
            currentTime={() => player.current?.currentTime ?? currentTime}
            onCreated={(annotation) => { setCreating(false); changed(); select(annotation) }}
            onClose={() => setCreating(false)} />
        )}
      </div>
    </div>
  )
}
