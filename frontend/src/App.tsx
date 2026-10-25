import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { Layout } from './components/Layout'
import { Loading } from './components/States'
import { Dashboard } from './pages/Dashboard'
import { DataView } from './pages/DataView'
import { Ingestion } from './pages/Ingestion'
import { Login } from './pages/Login'
import { NotFound } from './pages/NotFound'
import { Participants } from './pages/Participants'
import { Review } from './pages/Review'
import { ClipReview } from './pages/ClipReview'
import { VideoView } from './pages/VideoView'

function Gate() {
  const { user } = useAuth()
  if (user === undefined) return <Loading what="session" />
  if (user === null) return <Login />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="review" element={<Review />} />
        <Route path="review/clips/:clipId" element={<ClipReview />} />
        <Route path="data" element={<DataView />} />
        <Route path="ingestion" element={<Ingestion />} />
        <Route path="videos/:videoId" element={<VideoView />} />
        <Route path="participants" element={<Participants />} />
        <Route path="participants/:personId" element={<Participants />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  )
}
