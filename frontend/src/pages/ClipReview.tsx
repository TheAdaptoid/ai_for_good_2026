import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { ClipPlayer } from '../components/ClipPlayer'
import { ClipReviewWidget } from '../components/ClipReviewWidget'
import { StoredClipPanel } from '../components/StoredClipPanel'
import { ErrorState, Loading } from '../components/States'
import { useResource } from '../hooks'
import { NotFound } from './NotFound'

export function ClipReview() {
  const navigate = useNavigate()
  const clipId = Number(useParams().clipId)
  const clip = useResource(() => api.personClip(clipId), [clipId])
  const [version, setVersion] = useState(0) // bumps after a review so the panel re-reads its summary
  if (clip.error instanceof ApiError && clip.error.status === 404) return <NotFound what="clip" />
  if (clip.error) return <ErrorState error={clip.error} onRetry={clip.reload} />
  if (!clip.data || clip.data.clip_id !== clipId) return <Loading what="clip" />

  return <div className="clip-review" key={clipId}>
    <div className="page-head"><div>
      <button type="button" className="back-button" onClick={() => void navigate('/review')}>Back to clips</button>
      <h1>Review clip #{clipId}</h1>
    </div></div>
    <ClipPlayer clip={clip.data} />
    <StoredClipPanel key={version} clip={clip.data} onClose={() => void navigate('/review')} />
    <ClipReviewWidget clip={clip.data} version={version} onChanged={() => { setVersion((v) => v + 1); clip.reload() }}
      onDeferred={() => void navigate('/review')} />
  </div>
}
