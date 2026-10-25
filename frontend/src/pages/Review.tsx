import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { DatabaseClips } from '../components/DatabaseClips'
import { ErrorState, Loading } from '../components/States'
import { useResource } from '../hooks'

export function Review() {
  const location = useLocation()
  const navigate = useNavigate()
  const message = location.state?.message
  const videos = useResource(api.videos, [])
  if (videos.error) return <ErrorState error={videos.error} onRetry={videos.reload} />
  if (!videos.data) return <Loading what="review" />

  return (
    <>
      <div className="page-head"><h1>Review</h1></div>
      {typeof message === 'string' && <div className="notice review-confirmation" role="status">
        {message}
        <button type="button" aria-label="Dismiss confirmation" onClick={() => void navigate(location.pathname + location.search, { replace: true, state: null })}>×</button>
      </div>}
      <DatabaseClips videos={videos.data} />
    </>
  )
}
