import { api } from '../api/client'
import { DatabaseClips } from '../components/DatabaseClips'
import { ErrorState, Loading } from '../components/States'
import { useResource } from '../hooks'

export function Review() {
  const videos = useResource(api.videos, [])
  if (videos.error) return <ErrorState error={videos.error} onRetry={videos.reload} />
  if (!videos.data) return <Loading what="review" />

  return (
    <>
      <div className="page-head"><h1>Review</h1></div>
      <DatabaseClips videos={videos.data} />
    </>
  )
}
