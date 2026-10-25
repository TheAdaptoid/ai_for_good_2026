import { useEffect, useRef, useState } from 'react'
import { api, type ActivityCount } from '../api/client'
import { useIntro, useResource } from '../hooks'
import { drawnShares } from '../pieShares'
import { Empty, ErrorState, Loading } from './States'

// Seven coloured slots: the ring closes on a gray slice, so the first and last colours never touch.
const SLOTS = 7
// The model's "no confident activity" result is not an activity, so it is drawn as neutral gray.
const NEUTRAL = new Set(['Uncertain result'])
const R = 90
const INNER = 56
const POP = 6 // hover offset in viewBox units; R + POP stays inside the 200-unit box

interface Slice { label: string; count: number; mean: number | null; color: string; members?: ActivityCount[] }

/**
 * Slices run largest to smallest, clockwise from the top. Activities take colour slots by rank, so
 * neighbouring slices are always the validated adjacent pairs; a per-label colour failed the
 * colour-blindness check once sorted by size. Uncertain results and "Other" (activities past
 * seven, always last) are gray. Ties sort by name.
 */
function slices(counts: ActivityCount[]): Slice[] {
  const byCount = [...counts].sort((a, b) => b.count - a.count || a.activity_label.localeCompare(b.activity_label))
  const activities = byCount.filter((c) => !NEUTRAL.has(c.activity_label))
  const folded = activities.slice(SLOTS)
  const result: Slice[] = activities.slice(0, SLOTS)
    .map((c, i) => ({ label: c.activity_label, count: c.count, mean: c.mean_positive_score ?? null, color: `var(--series-${i + 1})` }))
  for (const c of byCount.filter((c) => NEUTRAL.has(c.activity_label))) {
    result.push({ label: c.activity_label, count: c.count, mean: c.mean_positive_score ?? null, color: 'var(--series-neutral)' })
  }
  result.sort((a, b) => b.count - a.count)
  // "Other" always closes the ring, even when its combined count outweighs a kept activity.
  if (folded.length) {
    const observations = folded.reduce((n, c) => n + (c.observation_count ?? 0), 0)
    result.push({ label: 'Other', count: folded.reduce((n, c) => n + c.count, 0), color: 'var(--series-other)', members: folded,
      // Observation-weighted, matching how each activity's own mean is computed.
      mean: observations ? folded.reduce((n, c) => n + (c.mean_positive_score ?? 0) * (c.observation_count ?? 0), 0) / observations : null })
  }
  return result
}

function arc(start: number, end: number): string {
  const point = (angle: number, radius: number) =>
    `${(100 + radius * Math.sin(angle)).toFixed(3)} ${(100 - radius * Math.cos(angle)).toFixed(3)}`
  const large = end - start > Math.PI ? 1 : 0
  return `M ${point(start, R)} A ${R} ${R} 0 ${large} 1 ${point(end, R)}`
    + ` L ${point(end, INNER)} A ${INNER} ${INNER} 0 ${large} 0 ${point(start, INNER)} Z`
}

const percent = (count: number, total: number) => `${((count / total) * 100).toFixed(1)}%`

const H = 400
const PAD = { top: 28, right: 8, bottom: 96, left: 56 }

/** Top-rounded bar anchored to the baseline (4px data-end radius). */
function bar(x: number, y: number, width: number, height: number): string {
  const r = Math.min(4, width / 2, height)
  return `M ${x} ${y + height} V ${y + r} Q ${x} ${y} ${x + r} ${y} H ${x + width - r} Q ${x + width} ${y} ${x + width} ${y + r} V ${y + height} Z`
}

/** Eases an array of numbers toward ``target`` (about 200ms); reduced motion and tests jump straight there. */
function useEased(target: number[]) {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  const key = target.join(',')
  useEffect(() => {
    const still = typeof window.matchMedia !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (still || from.current.length !== target.length) {
      from.current = target
      setValue(target) // oxlint-disable-line react/set-state-in-effect -- snap without animating
      return
    }
    const start = performance.now()
    const begin = from.current
    let frame = 0
    const step = (now: number) => {
      const p = Math.min(1, Math.max(0, (now - start) / 200))
      const e = 1 - (1 - p) ** 3
      const next = target.map((v, i) => begin[i] + (v - begin[i]) * e)
      from.current = next
      setValue(next)
      if (p < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps -- key captures target's contents
  return value
}

/** Width of an element in CSS pixels, so the SVG is drawn 1:1 and its text never scales. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(320, Math.round(entry.contentRect.width))))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

function AffectBars({ data, active, setActive, t }: { data: Slice[]; active: string | null; setActive: (label: string | null) => void; t: number }) {
  const [ref, W] = useWidth(640)
  // Highest mean first; each bar keeps its pie colour. Activities without observations go last.
  const bars = [...data].sort((a, b) => (b.mean ?? -1) - (a.mean ?? -1) || b.count - a.count)
  const max = Math.max(0.1, ...data.map((s) => s.mean ?? 0))
  const top = Math.ceil(max * 10) / 10
  const ticks = Array.from({ length: Math.round(top / 0.1) + 1 }, (_, i) => i * 0.1)
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const slot = plotW / bars.length
  const barW = Math.min(72, slot * 0.7, slot - 2) // at least a 2px surface gap between neighbours
  const rotate = slot < 150 // long names fit level only when each column is wide
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH
  return (
    <div ref={ref} className="affect-bars-wrap">
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="affect-bars" role="img"
      aria-label="Bar chart of mean positive visible-affect score by activity" onMouseLeave={() => setActive(null)}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 0 ? 'axis-line' : 'grid-line'} />
          <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="axis-text">{t.toFixed(1)}</text>
        </g>
      ))}
      <text transform={`translate(14 ${PAD.top + plotH / 2}) rotate(-90)`} textAnchor="middle" className="axis-title">Mean positive score</text>
      {bars.map((s, i) => {
        const cx = PAD.left + slot * i + slot / 2
        const label = rotate && s.label.length > 18 ? `${s.label.slice(0, 17)}…` : s.label
        return (
          <g key={s.label} className="bar-group"
            onMouseEnter={() => setActive(s.label)}>
            {/* Hit target spans the whole column, larger than the mark. */}
            <rect x={cx - slot / 2} y={PAD.top} width={slot} height={plotH} fill="transparent" />
            {s.mean === null
              ? <text x={cx} y={y(0) - 6} textAnchor="middle" className="axis-text">no data</text>
              : <path d={bar(cx - barW / 2, y(s.mean * t), barW, y(0) - y(s.mean * t))} fill={s.color} className={`slice ${active === s.label ? 'slice--active' : ''}`}
                  tabIndex={0} aria-label={`${s.label}: mean positive score ${s.mean.toFixed(3)}`}
                  onFocus={() => setActive(s.label)} onBlur={() => setActive(null)}>
                  <title>{`${s.label}: ${s.mean.toFixed(3)}`}</title>
                </path>}
            {active === s.label && s.mean !== null &&
              <text x={cx} y={y(s.mean * t) - 8} textAnchor="middle" className="bar-value">{(s.mean * t).toFixed(3)}</text>}
            {rotate
              ? <text transform={`translate(${cx} ${y(0) + 16}) rotate(-35)`} textAnchor="end" className="axis-text">{label}</text>
              : <text x={cx} y={y(0) + 22} textAnchor="middle" className="axis-text">{label}</text>}
          </g>
        )
      })}
    </svg>
    </div>
  )
}

export function ActivityPie() {
  const counts = useResource(api.activityCounts, [])
  const [active, setActive] = useState<string | null>(null)
  // Animated values only; aria-labels and tooltips always carry the final numbers.
  const t = useIntro(Boolean(counts.data?.length))
  const data = counts.data ? slices(counts.data) : []
  const drawn = useEased(drawnShares(data.map((s) => s.count), data.findIndex((s) => s.label === active)))

  return (
    <section className="queue activity-widget" aria-labelledby="activity-chart-title">
      <h2 id="activity-chart-title">Activities by frequency</h2>
      <p className="muted small">
        Current activity label of every analyzed window: model suggestions plus staff corrections.
        Counts are windows, not people or minutes. Hovering a small slice enlarges it to be seen; the legend
        gives exact shares. The bars show the mean positive visible-affect score of
        the face observations inside each activity's windows: an observable signal, not an emotional state.
      </p>
      {counts.error && <ErrorState error={counts.error} onRetry={counts.reload} />}
      {!counts.data && !counts.error && <Loading what="activity counts" />}
      {counts.data && counts.data.length === 0 && <Empty>No activity results in the database yet.</Empty>}
      {counts.data && counts.data.length > 0 && (() => {
        const total = data.reduce((n, s) => n + s.count, 0)
        const shown = data.find((s) => s.label === active)
        let angle = 0
        return (
          <div className="activity-chart">
            <svg viewBox="0 0 200 200" role="img" aria-label={`Pie chart of ${total} activity windows by label`}
              onMouseLeave={() => setActive(null)}>
              {data.length === 1
                ? <circle cx="100" cy="100" r={(R + INNER) / 2} fill="none" stroke={data[0].color} strokeWidth={R - INNER} />
                : data.map((s, i) => {
                  const start = angle
                  angle += drawn[i] * 2 * Math.PI * t
                  const mid = (start + angle) / 2 // the active slice slides out along its centre line
                  return (
                    <path key={s.label} d={arc(start, angle)} fill={s.color} stroke="var(--chart-bg, var(--surface))" strokeWidth="2"
                      strokeLinejoin="round" tabIndex={0} aria-label={`${s.label}: ${s.count} windows, ${percent(s.count, total)}`}
                      className={`slice ${active === s.label ? 'slice--active' : ''}`}
                      style={active === s.label ? { transform: `translate(${(POP * Math.sin(mid)).toFixed(2)}px, ${(-POP * Math.cos(mid)).toFixed(2)}px)` } : undefined}
                      onMouseEnter={() => setActive(s.label)} onFocus={() => setActive(s.label)} onBlur={() => setActive(null)}>
                      <title>{`${s.label}: ${s.count} (${percent(s.count, total)})`}</title>
                    </path>
                  )
                })}
              <text x="100" y="98" textAnchor="middle" className="pie-center__value">
                {shown ? percent(shown.count * t, total) : Math.round(total * t)}
              </text>
              <text x="100" y="118" textAnchor="middle" className="pie-center__label">
                {shown ? shown.label.slice(0, 22) : 'windows'}
              </text>
            </svg>
            <ul className="activity-legend" aria-label="Activity counts">
              <li className="activity-legend__head" aria-hidden="true">
                <span /><span>Activity</span><span className="count">Windows</span><span className="share">Share</span><span className="mean">Mean positive</span>
              </li>
              {data.map((s) => (
                <li key={s.label} className={active === s.label ? 'legend--active' : undefined}
                  onMouseEnter={() => setActive(s.label)} onMouseLeave={() => setActive(null)}
                  title={s.members?.map((m) => `${m.activity_label}: ${m.count}`).join('\n')}>
                  <span className="swatch-dot" style={{ background: s.color }} aria-hidden="true" />
                  <span>{s.label}{s.members && <span className="muted small"> ({s.members.length} labels)</span>}</span>
                  <span className="count">{Math.round(s.count * t)}</span>
                  <span className="share">{percent(s.count * t, total)}</span>
                  <span className="mean">{s.mean === null ? '—' : (s.mean * t).toFixed(3)}</span>
                </li>
              ))}
            </ul>
            <AffectBars data={data} active={active} setActive={setActive} t={t} />
          </div>
        )
      })()}
    </section>
  )
}
