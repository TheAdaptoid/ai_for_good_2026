import { useEffect, useState } from 'react'
import { api, type VideoProgress } from '../api/client'
import { Empty, ErrorState, Loading } from '../components/States'

const STAGES = [
  { key: 'activity', label: 'Activity', unit: 'frames', hint: 'Frames with a face that have an activity result.' },
  { key: 'engagement', label: 'Engagement', unit: 'detections', hint: 'Face detections with visible-affect scores.' },
  { key: 'clips', label: 'Clips', unit: 'videos', hint: 'Videos whose person clips are finalized.' },
] as const

type StageKey = (typeof STAGES)[number]['key']
const REFRESH_MS = 3_000

interface ProgressSnapshot {
  data?: VideoProgress[]
  error?: Error
  refreshedAt?: Date
}

function stage(video: VideoProgress, key: StageKey) {
  return video.stages.find((s) => s.stage === key) ?? { stage: key, done: 0, total: 0 }
}

function state(done: number, total: number) {
  if (total === 0) return 'Nothing to process'
  if (done >= total) return 'Complete'
  return done === 0 ? 'Not started' : 'In progress'
}

/** Accessible bar: the text beside it carries the numbers, so colour is never the only cue. */
function Bar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = total ? (done / total) * 100 : 0
  return (
    <div className={`progress ${total && done >= total ? 'progress--done' : ''}`} role="progressbar" aria-label={label}
      aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-valuetext={`${done} of ${total} (${pct.toFixed(1)}%)`}>
      <span style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Ingestion() {
  const [progress, setProgress] = useState<ProgressSnapshot>({})
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    let timer: number | undefined
    async function refresh() {
      try {
        const data = await api.processing()
        if (active) setProgress({ data, refreshedAt: new Date() })
      } catch (error) {
        if (active) setProgress((previous) => ({ ...previous,
          error: error instanceof Error ? error : new Error('Could not refresh processing progress'),
        }))
      } finally {
        // Schedule only after completion, so a slow query cannot create overlapping polls.
        if (active) timer = window.setTimeout(refresh, REFRESH_MS)
      }
    }
    void refresh()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [attempt])

  if (progress.error && !progress.data) return <ErrorState error={progress.error} onRetry={() => setAttempt((value) => value + 1)} />
  if (!progress.data) return <Loading what="processing progress" />
  const videos = progress.data
  const totals = STAGES.map(({ key }) => videos.reduce((sum, v) => {
    const s = stage(v, key)
    return { done: sum.done + s.done, total: sum.total + s.total }
  }, { done: 0, total: 0 }))

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Data Ingestion</h1>
          <p className="muted">Processing progress for every video, read from the analysis database. Updates every 3 seconds.</p>
          {progress.refreshedAt && <p className="muted small">Last refreshed{' '}
            <time dateTime={progress.refreshedAt.toISOString()}>{progress.refreshedAt.toLocaleTimeString()}</time>
          </p>}
        </div>
      </div>
      {progress.error && <p className="notice" role="status">Refresh failed. Showing the last received counts and retrying automatically.</p>}
      {videos.length === 0 ? <Empty>No videos in the database yet.</Empty> : <>
        <section className="stage-cards" aria-label="Overall progress">
          {STAGES.map(({ key, label, unit, hint }, i) => {
            const { done, total } = totals[i]
            return (
              <div className="stage-card" key={key}>
                <div className="stage-card__head">
                  <h2>{label}</h2>
                  <span className={`stage-state stage-state--${state(done, total).replace(/ /g, '-').toLowerCase()}`}>{state(done, total)}</span>
                </div>
                <p className="stage-card__pct">{total ? ((done / total) * 100).toFixed(1) : '0.0'}%</p>
                <Bar done={done} total={total} label={`${label} overall`} />
                <p className="muted small">{done.toLocaleString()} of {total.toLocaleString()} {unit} · {(total - done).toLocaleString()} left. {hint}</p>
              </div>
            )
          })}
        </section>

        <section className="queue" aria-labelledby="per-video-title">
          <h2 id="per-video-title">By video</h2>
          <div className="table-wrap" role="region" aria-label="Progress by video" tabIndex={0}>
            <table className="videos progress-table">
              <thead>
                <tr><th scope="col">Video</th>{STAGES.map(({ key, label }) => <th scope="col" key={key}>{label}</th>)}</tr>
              </thead>
              <tbody>
                {videos.map((video) => (
                  <tr key={video.video_id}>
                    <th scope="row">{video.title}</th>
                    {STAGES.map(({ key, label }) => {
                      const { done, total } = stage(video, key)
                      return (
                        <td key={key}>
                          <Bar done={done} total={total} label={`${label}: ${video.title}`} />
                          <span className="progress-cell__text">
                            {total ? `${done.toLocaleString()} / ${total.toLocaleString()}` : '—'} · {state(done, total)}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </>}
    </>
  )
}
