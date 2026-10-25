const SMALL = 0.02
const BOOST = 3

/**
 * Drawn share of each slice. At rest the pie is to scale; a highlighted slice under SMALL is drawn
 * BOOST times its size and the others shrink in proportion. Display only: labels, legend, and aria
 * text keep the exact shares. The enlarged slice always still covers the pointer that highlighted
 * it (its start can only move back, its end only forward), so hover never flickers.
 */
export function drawnShares(counts: number[], active = -1): number[] {
  const total = counts.reduce((n, c) => n + c, 0)
  if (!total) return counts.map(() => 0)
  const shares = counts.map((c) => c / total)
  const own = shares[active]
  if (own === undefined || own >= SMALL) return shares
  const scale = (1 - own * BOOST) / (1 - own)
  return shares.map((s, i) => (i === active ? own * BOOST : s * scale))
}
