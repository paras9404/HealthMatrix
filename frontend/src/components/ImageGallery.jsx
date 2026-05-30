import { useState, useEffect, useRef, useCallback } from 'react'
import './ImageGallery.css'

const TYPE_LABELS = {
  main: 'Product',
  ingredients: 'Ingredients',
  nutrition_facts: 'Nutrition Facts',
  back: 'Back',
  side: 'Side',
  box: 'Packaging',
  label: 'Label',
  lifestyle: 'Lifestyle',
  other: 'Other',
}

export default function ImageGallery({ images, fallbackEmoji, alt }) {
  const [active, setActive] = useState(0)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [lensPos, setLensPos] = useState(null)        // {x,y} percentage on main image
  const stageRef = useRef(null)
  const startX = useRef(null)

  const list = Array.isArray(images) && images.length > 0 ? images : null

  useEffect(() => { setActive(0) }, [list?.[0]?.url])

  const goTo = useCallback((idx) => {
    if (!list) return
    const next = ((idx % list.length) + list.length) % list.length
    setActive(next)
  }, [list])

  const next = useCallback(() => goTo(active + 1), [active, goTo])
  const prev = useCallback(() => goTo(active - 1), [active, goTo])

  // touch swipe on stage
  const onTouchStart = (e) => { startX.current = e.touches[0].clientX }
  const onTouchEnd = (e) => {
    if (startX.current == null) return
    const dx = e.changedTouches[0].clientX - startX.current
    if (Math.abs(dx) > 40) (dx < 0 ? next : prev)()
    startX.current = null
  }

  // Hover magnifier. The lens always renders as a square, and the right-hand
  // zoom panel (also square) shows exactly the same square region of the image —
  // at natural aspect, no stretching, regardless of whether the source image is
  // square, portrait, or landscape.
  //
  // Math:
  //   • Lens side `ls = min(rw, rh) / Z` so the lens always fits inside the image.
  //   • Per-axis effective zoom: effZx = rw/ls, effZy = rh/ls (effZx == effZy == Z
  //     for a square image; one stays Z and the other grows for non-square images).
  //   • bg-size in each axis = effZ * 100% so a `ls × ls` stage area maps to the
  //     full `pw × pw` panel.
  //   • bg-position per axis: `P% = (c · effZ − 0.5) / (effZ − 1) × 100`, clamped
  //     to [0, 100]. CSS bg-position aligns the P% point of the image with the
  //     P% point of the container, so this places the cursor's image fraction at
  //     the panel's center (clamped at edges so the panel can't scroll off-image).
  const ZOOM = 2.5
  const onMouseMove = (e) => {
    const stage = stageRef.current
    if (!stage || lightboxOpen) return
    const imgEl = stage.querySelector('img.gallery-img')
    if (!imgEl || !imgEl.naturalWidth) return

    const sr = stage.getBoundingClientRect()
    // Stage has 16px padding around the image; object-fit: contain centers the
    // image inside that content box. Compute the actual rendered image rect.
    const pad = 16
    const cw = sr.width - 2 * pad
    const ch = sr.height - 2 * pad
    const ratio = imgEl.naturalWidth / imgEl.naturalHeight
    let rw, rh, ox, oy
    if (cw / ch > ratio) {
      rh = ch; rw = rh * ratio
      ox = pad + (cw - rw) / 2
      oy = pad
    } else {
      rw = cw; rh = rw / ratio
      ox = pad
      oy = pad + (ch - rh) / 2
    }

    const sx = e.clientX - sr.left
    const sy = e.clientY - sr.top
    const ls = Math.min(rw, rh) / ZOOM       // square lens side
    const lcx = Math.max(ox + ls / 2, Math.min(ox + rw - ls / 2, sx))
    const lcy = Math.max(oy + ls / 2, Math.min(oy + rh - ls / 2, sy))
    const cx = Math.max(0, Math.min(1, (sx - ox) / rw))
    const cy = Math.max(0, Math.min(1, (sy - oy) / rh))
    const effZx = rw / ls                     // = ZOOM for square/portrait, > ZOOM for landscape
    const effZy = rh / ls                     // = ZOOM for square/landscape, > ZOOM for portrait
    const bgX = Math.max(0, Math.min(100, ((cx * effZx - 0.5) / (effZx - 1)) * 100))
    const bgY = Math.max(0, Math.min(100, ((cy * effZy - 0.5) / (effZy - 1)) * 100))
    const bgSizeX = effZx * 100
    const bgSizeY = effZy * 100

    setLensPos({ lcx, lcy, ls, bgX, bgY, bgSizeX, bgSizeY })
  }
  const onMouseLeave = () => setLensPos(null)

  // keyboard nav (works while gallery is focused, and globally while lightbox open)
  useEffect(() => {
    const onKey = (e) => {
      if (lightboxOpen) {
        if (e.key === 'Escape') setLightboxOpen(false)
        else if (e.key === 'ArrowLeft') prev()
        else if (e.key === 'ArrowRight') next()
        return
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lightboxOpen, next, prev])

  if (!list) {
    return (
      <div className="gallery">
        <div className="gallery-stage gallery-empty">
          <span>{fallbackEmoji || '📦'}</span>
        </div>
      </div>
    )
  }

  const current = list[active]
  const showThumbs = list.length > 1

  return (
    <>
      <div className={`gallery gallery-amazon${showThumbs ? '' : ' gallery-no-thumbs'}`}>
        {showThumbs && (
          <div className="gallery-thumbs-vertical" role="tablist" aria-label="Product images">
            {list.map((img, i) => (
              <button
                key={img.id ?? i}
                type="button"
                role="tab"
                aria-selected={i === active}
                aria-label={`Show ${TYPE_LABELS[img.type] || img.type} image`}
                className={`gallery-thumb ${i === active ? 'active' : ''}`}
                onMouseEnter={() => goTo(i)}
                onClick={() => goTo(i)}
                title={TYPE_LABELS[img.type] || img.type}
              >
                <img src={img.url} alt={img.alt || `Thumbnail ${i + 1}`} loading="lazy" />
              </button>
            ))}
          </div>
        )}

        <div
          ref={stageRef}
          className="gallery-stage"
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
          onMouseMove={onMouseMove}
          onMouseLeave={onMouseLeave}
          onClick={() => setLightboxOpen(true)}
          role="button"
          tabIndex={0}
          aria-label={`${current.alt || alt}. Click to expand.`}
        >
          <img
            key={current.url}
            src={current.url}
            alt={current.alt || alt || `Image ${active + 1}`}
            className="gallery-img"
            loading="eager"
          />
          {current.type && current.type !== 'main' && (
            <span className="gallery-type-badge">{TYPE_LABELS[current.type] || current.type}</span>
          )}
          <button
            type="button"
            className="gallery-expand-hint"
            aria-label="Open fullscreen"
            onClick={(e) => { e.stopPropagation(); setLightboxOpen(true) }}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path fill="currentColor" d="M4 4h6v2H6v4H4V4zm10 0h6v6h-2V6h-4V4zM4 14h2v4h4v2H4v-6zm14 0h2v6h-6v-2h4v-4z"/>
            </svg>
          </button>
          {showThumbs && lensPos === null && (
            <>
              <button
                type="button"
                className="gallery-arrow gallery-arrow-prev"
                onClick={(e) => { e.stopPropagation(); prev() }}
                aria-label="Previous image"
              >‹</button>
              <button
                type="button"
                className="gallery-arrow gallery-arrow-next"
                onClick={(e) => { e.stopPropagation(); next() }}
                aria-label="Next image"
              >›</button>
            </>
          )}
          {lensPos && (
            <span
              className="gallery-lens"
              style={{
                left: `${lensPos.lcx}px`,
                top: `${lensPos.lcy}px`,
                width: `${lensPos.ls}px`,
                height: `${lensPos.ls}px`,
              }}
              aria-hidden="true"
            />
          )}
        </div>

        {/* Right-hand magnified panel — appears on hover, desktop only */}
        {lensPos && (
          <div className="gallery-zoom-panel" aria-hidden="true">
            <div
              className="gallery-zoom-img"
              style={{
                backgroundImage: `url(${current.url})`,
                backgroundSize: `${lensPos.bgSizeX}% ${lensPos.bgSizeY}%`,
                backgroundPosition: `${lensPos.bgX}% ${lensPos.bgY}%`,
              }}
            />
          </div>
        )}
      </div>

      {lightboxOpen && (
        <Lightbox
          images={list}
          active={active}
          onClose={() => setLightboxOpen(false)}
          onPrev={prev}
          onNext={next}
          onSelect={goTo}
        />
      )}
    </>
  )
}


function Lightbox({ images, active, onClose, onPrev, onNext, onSelect }) {
  const [scale, setScale] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const dragRef = useRef(null)
  const startX = useRef(null)

  useEffect(() => { setScale(1); setPan({ x: 0, y: 0 }) }, [active])

  // Lock body scroll while lightbox is open
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  const current = images[active]

  const handleWheel = (e) => {
    e.preventDefault()
    const next = Math.max(1, Math.min(4, scale + (e.deltaY < 0 ? 0.25 : -0.25)))
    setScale(next)
    if (next === 1) setPan({ x: 0, y: 0 })
  }

  const onPointerDown = (e) => {
    if (scale === 1) { startX.current = e.clientX; return }
    dragRef.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y }
  }
  const onPointerMove = (e) => {
    if (!dragRef.current) return
    setPan({
      x: dragRef.current.panX + (e.clientX - dragRef.current.x),
      y: dragRef.current.panY + (e.clientY - dragRef.current.y),
    })
  }
  const onPointerUp = (e) => {
    if (startX.current != null && scale === 1) {
      const dx = e.clientX - startX.current
      if (dx > 60) onPrev()
      else if (dx < -60) onNext()
    }
    startX.current = null
    dragRef.current = null
  }

  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-modal="true" aria-label="Image viewer">
      <button type="button" className="lightbox-close" onClick={onClose} aria-label="Close">
        <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M6.4 4.99 12 10.59l5.59-5.6 1.41 1.41L13.41 12 19 17.59 17.59 19 12 13.41 6.41 19 5 17.59 10.59 12 5 6.4z"/></svg>
      </button>

      <div className="lightbox-counter">{active + 1} / {images.length}</div>

      <button type="button" className="lightbox-arrow lightbox-arrow-prev" onClick={(e) => { e.stopPropagation(); onPrev() }} aria-label="Previous">‹</button>

      <div
        className="lightbox-stage"
        onClick={(e) => e.stopPropagation()}
        onWheel={handleWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        style={{ cursor: scale > 1 ? (dragRef.current ? 'grabbing' : 'grab') : 'zoom-in' }}
      >
        <img
          src={current.url}
          alt={current.alt || `Image ${active + 1}`}
          className="lightbox-img"
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }}
          onDoubleClick={() => { setScale(scale === 1 ? 2 : 1); setPan({ x: 0, y: 0 }) }}
          draggable={false}
        />
      </div>

      <button type="button" className="lightbox-arrow lightbox-arrow-next" onClick={(e) => { e.stopPropagation(); onNext() }} aria-label="Next">›</button>

      <div className="lightbox-thumbs" onClick={(e) => e.stopPropagation()}>
        {images.map((img, i) => (
          <button
            key={img.id ?? i}
            type="button"
            className={`lightbox-thumb ${i === active ? 'active' : ''}`}
            onClick={() => onSelect(i)}
            aria-label={`Show image ${i + 1}`}
          >
            <img src={img.url} alt="" loading="lazy" />
          </button>
        ))}
      </div>

      <div className="lightbox-zoom-controls" onClick={(e) => e.stopPropagation()}>
        <button type="button" onClick={() => setScale(Math.max(1, scale - 0.5))} aria-label="Zoom out">−</button>
        <span>{Math.round(scale * 100)}%</span>
        <button type="button" onClick={() => setScale(Math.min(4, scale + 0.5))} aria-label="Zoom in">+</button>
      </div>
    </div>
  )
}
