import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Agentation } from 'agentation'
import { App } from './App'
import './styles.css'

if (import.meta.env.DEV) {
  try {
    localStorage.setItem('feedback-toolbar-theme', 'light')
  } catch {
    // Feedback storage can be disabled by browser privacy settings.
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    {import.meta.env.DEV && <Agentation endpoint="http://localhost:4747" appName="TPA Video Review" />}
  </StrictMode>,
)
