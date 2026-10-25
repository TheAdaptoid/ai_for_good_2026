import type { Annotation } from '../api/client'

/** Source and review status are separate facts, so they are always shown as two badges. */
export function StatusBadges({ annotation }: { annotation: Pick<Annotation, 'source' | 'review_status'> }) {
  return (
    <span className="badges">
      <span className={`badge badge--source-${annotation.source.toLowerCase()}`} title="Source of the current value">
        Source: {annotation.source}
      </span>
      <span className={`badge badge--status-${annotation.review_status.toLowerCase()}`} title="Review status">
        {annotation.review_status}
      </span>
    </span>
  )
}
