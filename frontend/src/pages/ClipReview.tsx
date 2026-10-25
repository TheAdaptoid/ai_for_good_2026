import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { ClipPlayer } from '../components/ClipPlayer'
import { ClipReviewWidget } from '../components/ClipReviewWidget'
import { StoredClipPanel } from '../components/StoredClipPanel'
import { ErrorState, Loading } from '../components/States'
import { useResource } from '../hooks'
import { NotFound } from './NotFound'

export function ClipReview() {
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from
  const returnTo = typeof from === 'string' && /^\/review(?:\?|$)/.test(from) ? from : '/review'
  const clipId = Number(useParams().clipId)
  const clip = useResource(() => api.personClip(clipId), [clipId])
  if (clip.error instanceof ApiError && clip.error.status === 404) return <NotFound what="clip" />
  if (clip.error) return <ErrorState error={clip.error} onRetry={clip.reload} />
  if (!clip.data || clip.data.clip_id !== clipId) return <Loading what="clip" />

  return <div className="clip-review" key={clipId}>
    <div className="clip-playback-card">
      <div className="page-head"><div>
        <button type="button" className="back-button" onClick={() => void navigate(returnTo)}>Back to clips</button>
        <h1>Review clip #{clipId}</h1>
      </div></div>
      <ClipPlayer clip={clip.data} />
    </div>
    <StoredClipPanel clip={clip.data} onClose={() => void navigate(returnTo)} />
    <ClipReviewWidget clip={clip.data}
      onReviewed={(status) => void navigate(returnTo, { state: { message: status === 'EDITED' ? `Changes to clip #${clipId} saved successfully.` : `Clip #${clipId} ${status.toLowerCase()}.` } })} />
  </div>
}
