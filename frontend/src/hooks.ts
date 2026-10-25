/* oxlint-disable react-hooks/exhaustive-deps -- useResource callers pass the inputs of `load` as deps */
import { useCallback, useEffect, useState } from 'react'

export interface Resource<T> {
  data: T | undefined
  error: Error | undefined
  loading: boolean
  reload: () => void
}

/** Load once per change of `deps`; `reload` re-fetches while keeping the current data on screen. */
export function useResource<T>(load: () => Promise<T>, deps: readonly unknown[]): Resource<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true })
  const [version, setVersion] = useState(0)
  useEffect(() => {
    let live = true
    // oxlint-disable-next-line react/set-state-in-effect -- marks the fetch below as in flight
    setState((current) => ({ data: current.data, loading: true }))
    load().then(
      (data) => live && setState({ data, loading: false }),
      (error: Error) => live && setState({ error, loading: false }),
    )
    return () => {
      live = false
    }
  }, [...deps, version])
  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return { data: state.data, error: state.error, loading: state.loading, reload }
}

/**
 * Intro progress from 0 to 1 (ease-out) once ``ready`` turns true, on page load or refresh.
 * Reduced-motion users, and environments without matchMedia (unit tests), start at 1.
 */
export function useIntro(ready: boolean, duration = 1000) {
  const still = typeof window.matchMedia !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const [t, setT] = useState(still ? 1 : 0)
  useEffect(() => {
    if (!ready || still) return
    let frame = 0
    const start = performance.now()
    const step = (now: number) => {
      const p = Math.min(1, Math.max(0, (now - start) / duration)) // a frame stamped before start must not go negative
      setT(1 - (1 - p) ** 3)
      if (p < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [ready, still, duration])
  return t
}
