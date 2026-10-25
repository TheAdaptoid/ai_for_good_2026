import type { ReactNode } from 'react'

export function Loading({ what }: { what: string }) {
  return (
    <p className="state" role="status">
      Loading {what}…
    </p>
  )
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <p>{error.message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state state--empty">{children}</p>
}
