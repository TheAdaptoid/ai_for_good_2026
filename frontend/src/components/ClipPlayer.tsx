import { useRef, useState } from 'react'
import { streamUrl, type PersonClip } from '../api/client'
import { formatTime } from '../format'

// Browsers round currentTime; seeking again for submillisecond differences can loop.
const TIME_TOLERANCE = 0.001

export function ClipPlayer({ clip }: { clip: PersonClip }) {
  const player = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [ready, setReady] = useState(false)
  const [missing, setMissing] = useState(false)
  const [error, setError] = useState('')
  const [position, setPosition] = useState(0)
  const duration = clip.end_seconds - clip.start_seconds
  const clamp = (time: number) => Math.min(clip.end_seconds, Math.max(clip.start_seconds, time))

  const synchronize = (video: HTMLVideoElement) => {
    const time = clamp(video.currentTime)
    if (Math.abs(time - video.currentTime) > TIME_TOLERANCE) video.currentTime = time
    if (time >= clip.end_seconds - TIME_TOLERANCE) video.pause()
    setPosition(time - clip.start_seconds)
  }

  const toggle = async () => {
    const video = player.current
    if (!video) return
    setError('')
    if (!video.paused) { video.pause(); return }
    if (video.currentTime >= clip.end_seconds - TIME_TOLERANCE || video.currentTime < clip.start_seconds - TIME_TOLERANCE) {
      video.currentTime = clip.start_seconds
    }
    try { await video.play() }
    catch { setError('Playback could not start. Try playing the clip again.') }
  }

  return (
    <section aria-label="Clip playback">
      {missing ? <div className="player player--missing" role="alert">The video file is unavailable on this machine.</div> : <>
        <video ref={player} className="player" aria-label={`Clip ${clip.clip_id}`} playsInline preload="auto"
          src={`${streamUrl(clip.video_id)}#t=${clip.start_seconds},${clip.end_seconds}`}
          onLoadedMetadata={(event) => { event.currentTarget.currentTime = clip.start_seconds; setReady(true) }}
          onSeeking={(event) => synchronize(event.currentTarget)}
          onTimeUpdate={(event) => synchronize(event.currentTarget)}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
          onError={() => { setMissing(true); setPlaying(false) }} />
        <div className="clip-controls">
          <button type="button" className="primary" disabled={!ready} onClick={() => void toggle()}>{playing ? 'Pause clip' : 'Play clip'}</button>
          <label>Clip position
            <input type="range" min={0} max={duration} step={0.01} value={position} disabled={!ready}
              aria-valuetext={`${formatTime(position)} of ${formatTime(duration)}`}
              onChange={(event) => {
                if (player.current) {
                  player.current.currentTime = clamp(clip.start_seconds + Number(event.target.value))
                  synchronize(player.current)
                }
              }} />
          </label>
          <span>{formatTime(position)} / {formatTime(duration)}</span>
        </div>
      </>}
      {error && <p role="alert" className="form-error">{error}</p>}
    </section>
  )
}
