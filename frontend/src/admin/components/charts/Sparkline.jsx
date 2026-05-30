/** Tiny inline-SVG sparkline + bar combo chart for the analytics page.
 *  No deps. Renders bars for `points` and a line on top.
 */
export default function Sparkline({
  points = [],
  height = 140,
  valueKey = 'page_views',
  labelKey = 'bucket',
  color = '#3b82f6',
  formatLabel = (s) => s,
  formatValue = (v) => v?.toLocaleString?.() ?? v,
}) {
  if (!points.length) {
    return <div className="admin-empty" style={{ padding: '24px 0' }}>No data in this range.</div>
  }
  const w = 100
  const h = 100
  const max = Math.max(1, ...points.map((p) => p[valueKey] || 0))
  const barW = w / points.length

  const linePts = points.map((p, i) => {
    const x = i * barW + barW / 2
    const y = h - ((p[valueKey] || 0) / max) * h
    return [x, y]
  })

  const path = linePts
    .map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`))
    .join(' ')

  return (
    <div style={{ width: '100%' }}>
      <div style={{ position: 'relative', width: '100%', height }}>
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          style={{ width: '100%', height: '100%', display: 'block' }}
        >
          {points.map((p, i) => {
            const v = p[valueKey] || 0
            const barH = (v / max) * h
            return (
              <rect
                key={i}
                x={i * barW + barW * 0.15}
                y={h - barH}
                width={barW * 0.7}
                height={barH}
                fill={color}
                opacity="0.18"
              >
                <title>{`${formatLabel(p[labelKey])}: ${formatValue(v)}`}</title>
              </rect>
            )
          })}
          <path d={path} stroke={color} strokeWidth="1.4" fill="none" vectorEffect="non-scaling-stroke" />
          {linePts.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="1.6" fill={color} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
      </div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', marginTop: 6,
        fontSize: 11, color: 'var(--text-secondary, #888)',
      }}>
        <span>{formatLabel(points[0][labelKey])}</span>
        <span>{formatLabel(points[points.length - 1][labelKey])}</span>
      </div>
    </div>
  )
}
