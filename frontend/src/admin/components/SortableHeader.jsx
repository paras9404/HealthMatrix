/**
 * Clickable <th> that drives a parent's sort state. Click cycles asc → desc on the
 * same column; clicking a different column switches to that column with `defaultDir`
 * (asc by default, desc for things like dates/scores where newest-first is natural).
 */
export default function SortableHeader({
  column,
  label,
  sort,
  dir,
  onSort,
  defaultDir = 'asc',
  align = 'left',
  style,
}) {
  const active = sort === column
  const nextDir = active ? (dir === 'asc' ? 'desc' : 'asc') : defaultDir

  return (
    <th
      className={`admin-sortable${active ? ' active' : ''}`}
      style={{ textAlign: align, ...style }}
      onClick={() => onSort(column, nextDir)}
      role="button"
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <span className="admin-sortable-inner">
        {label}
        <span className={`admin-sortable-icon${active ? '' : ' muted'}`} aria-hidden="true">
          {active ? (dir === 'asc' ? '▲' : '▼') : '▲▼'}
        </span>
      </span>
    </th>
  )
}
