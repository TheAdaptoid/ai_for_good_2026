import { Link } from 'react-router-dom'

export function NotFound({ what = 'page' }: { what?: string }) {
  return (
    <div className="state state--error" role="alert">
      <p>This {what} was not found.</p>
      <Link to="/">Back to the dashboard</Link>
    </div>
  )
}
