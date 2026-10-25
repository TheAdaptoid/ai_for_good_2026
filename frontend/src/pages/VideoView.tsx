import { useCallback, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, streamUrl, type Annotation, type ReviewClip } from '../api/client'
import { ClipPanel } from '../components/ClipPanel'
import { CreateForm } from '../components/CreateForm'
import { ReviewPanel } from '../components/ReviewPanel'
import { ErrorState, Loading } from '../components/States'
import { Timeline } from '../components/Timeline'
import { formatTime } from '../format'
import { useResource } from '../hooks'
import { NotFound } from './NotFound'

export function VideoView() {
  const videoId = Number(useParams().videoId)
  const [params, setParams] = useSearchParams()
  const startAt = Number(params.get('t') ?? 0)
  const selectedId = params.get('annotation') ? Number(params.get('annotation')) : null
  const clipId = params.get('clip') ? Number(params.get('clip')) : null
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
      return next
    }, { replace: true })
  }, [setParams])
  const selectClip = useCallback((clip: ReviewClip) => {
    setCreating(false)
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('clip', String(clip.clip_id))
      next.delete('annotation')
      return next
    }, { replace: true })
  }, [setParams])
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
          <p className="crumbs"><Link to="/">Dashboard</Link> /</p>
          <h1>{summary.title}</h1>
          <p className="muted">
            {formatTime(duration)} · {summary.participant_count} anonymous participants ·{' '}
            {summary.clip_count} review clips
          </p>
        </div>
        <button type="button" className="primary" disabled={!fps || !labels.data}
          onClick={() => { closePanel(); closeClip(); setCreating(true) }}>
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
            <label className="check">
              <input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} />
              Show rejected annotations
            </label>
            <span className="legend">
              <span className="legend__item"><i className="swatch swatch--presence" /> on screen (face detections)</span>
              <span className="legend__item"><i className="swatch swatch--activity" /> activity</span>
              <span className="legend__item"><i className="swatch swatch--observation" /> observation</span>
              <span className="legend__item"><i className="swatch swatch--suggestion" /> unreviewed AI suggestion</span>
            </span>
          </div>

          {participants.error && <ErrorState error={participants.error} onRetry={participants.reload} />}
          {annotations.error && <ErrorState error={annotations.error} onRetry={annotations.reload} />}
          {clips.error && <ErrorState error={clips.error} onRetry={clips.reload} />}
          {participants.data && annotations.data && clips.data && duration > 0 ? (
            <Timeline duration={duration} clips={clips.data} annotations={annotations.data}
              participants={participants.data} currentTime={currentTime} selectedId={selectedId}
              selectedClipId={clipId} onSeek={seek} onSelect={select} onSelectClip={selectClip} />
          ) : (
            !participants.error && !annotations.error && !clips.error && <Loading what="timeline" />
          )}
        </div>

        {selected.data && labels.data && (
          <ReviewPanel key={selected.data.annotation_id} annotation={selected.data} labels={labels.data} fps={fps}
            participantIds={participantIds} onChanged={changed} onClose={closePanel} />
        )}
        {!selected.data && !creating && selectedClip.data && (
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
