// Authored line icons on a 24px grid, one 1.75 stroke, so every icon in the app shares a weight.
const PATHS = {
  dashboard: 'M4 4h7v8H4zM13 4h7v5h-7zM13 11h7v9h-7zM4 14h7v6H4z',
  review: 'M9 4h6M9 4a1 1 0 0 0-1 1v1h8V5a1 1 0 0 0-1-1M8 6H6v14h12V6h-2M9 13l2 2 4-4',
  participants: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3 20a6 6 0 0 1 12 0M16 4.5a3.5 3.5 0 0 1 0 6.5M18 14.5a6 6 0 0 1 3 5.5',
  data: 'M4 5h16v14H4zM4 10h16M4 15h16M10 5v14',
  signOut: 'M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 16l-4-4 4-4M6 12h10',
  video: 'M4 6h16v12H4zM10 9.5v5l4.5-2.5z',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  clips: 'M4 7h16v10H4zM8 7v10M16 7v10M4 12h4M16 12h4',
  pen: 'M15 5l4 4M4 20l1-5L16 4l4 4L9 19z',
  ingest: 'M12 4v10M8 10l4 4 4-4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3',
  first: 'M17 18l-6-6 6-6M11 18l-6-6 6-6',
  previous: 'M15 18l-6-6 6-6',
  next: 'M9 18l6-6-6-6',
  last: 'M7 18l6-6-6-6M13 18l6-6-6-6',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={className ?? 'icon'} viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
      strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  )
}
