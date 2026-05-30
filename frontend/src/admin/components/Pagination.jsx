export default function Pagination({ page, totalPages, total, onChange }) {
  if (!totalPages || totalPages <= 1) {
    return total ? <div className="admin-pagination"><span className="info">{total} total</span></div> : null
  }
  return (
    <div className="admin-pagination">
      <button className="admin-btn secondary sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>← Prev</button>
      <span className="info">Page {page} of {totalPages} · {total} total</span>
      <button className="admin-btn secondary sm" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>Next →</button>
    </div>
  )
}
