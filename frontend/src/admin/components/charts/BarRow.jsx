/** Horizontal bar list for "top X" tables. Shows label + count + relative bar. */
export default function BarRow({ items = [], labelKey = 'label', valueKey = 'count', renderLabel, emptyText = 'No data.' }) {
  if (!items.length) {
    return <div className="admin-empty" style={{ padding: '12px 0' }}>{emptyText}</div>
  }
  const max = Math.max(1, ...items.map((it) => it[valueKey] || 0))

  return (
    <div className="admin-bar-list">
      {items.map((it, i) => {
        const v = it[valueKey] || 0
        const pct = (v / max) * 100
        return (
          <div className="admin-bar-row" key={i}>
            <div className="admin-bar-label" title={typeof it[labelKey] === 'string' ? it[labelKey] : ''}>
              {renderLabel ? renderLabel(it) : (it[labelKey] || '—')}
            </div>
            <div className="admin-bar-track">
              <div className="admin-bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <div className="admin-bar-value">{v.toLocaleString()}</div>
          </div>
        )
      })}
    </div>
  )
}
