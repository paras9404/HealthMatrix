import { useState } from 'react'
import './LabLogo.css'

const VARIANTS = {
  'labdoor':         { shape: 'shield',  abbr: 'LD',  tag: 'LABDOOR' },
  'consumerlab':     { shape: 'beaker',  abbr: 'CL',  tag: 'ConsumerLab' },
  'nsf':             { shape: 'circle',  abbr: 'NSF', tag: 'NSF' },
  'usp':             { shape: 'hex',     abbr: 'USP', tag: 'USP' },
  'examine':         { shape: 'square',  abbr: 'Ex',  tag: 'Examine' },
  'trustified':      { shape: 'check',   abbr: 'TR',  tag: 'Trustified' },
  'informed-choice': { shape: 'circle',  abbr: 'IC',  tag: 'Informed Choice' },
  'informed-sport':  { shape: 'shield',  abbr: 'IS',  tag: 'Informed Sport' },
  'trustpilot':      { shape: 'star',    abbr: '★',   tag: 'Trustpilot' },
}

export default function LabLogo({ source }) {
  const [imgFailed, setImgFailed] = useState(false)
  if (!source) return null
  const slug = source.slug || ''
  const fallback = { shape: 'circle', abbr: (source.name || '?').slice(0, 2), tag: source.name }
  const v = VARIANTS[slug] || fallback
  const color = source.color || source.brand_color || '#0F766E'
  const logoSrc = !imgFailed ? source.logo_url : null
  return (
    <div className="lab-logo" style={{ '--lab-color': color }}>
      <div className={`lab-mark lab-${v.shape}`}>
        {logoSrc ? (
          <img
            className="lab-mark-img"
            src={logoSrc}
            alt={v.tag}
            onError={() => setImgFailed(true)}
          />
        ) : (
          <span>{v.abbr}</span>
        )}
      </div>
      <div className="lab-text">
        <strong>{v.tag}</strong>
        <span>{source.is_verified ?? source.verified ? '✓ Verified lab' : 'Reviews source'}</span>
      </div>
    </div>
  )
}
