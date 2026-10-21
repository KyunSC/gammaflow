'use client'

/**
 * A titled region of the one surface. No card, no shadow: a hairline above
 * and a sans-serif heading, so the title reads as a heading rather than as
 * another 10px label competing with the numbers under it.
 */
export default function Section({ title, meta, right, children, className = '', bodyClassName = '', scroll = true, id, as: Tag = 'section' }) {
  return (
    <Tag className={`v6-sec ${className}`} aria-label={typeof title === 'string' ? title : undefined} id={id}>
      {(title || right) && (
        <header className="v6-sec-head">
          {title && <h2 className="v6-h">{title}</h2>}
          {meta && <span className="v6-sec-meta">{meta}</span>}
          <span className="min-w-0 flex-1" />
          {right}
        </header>
      )}
      <div className={`v6-sec-body ${scroll ? 'overflow-auto' : 'overflow-hidden'} ${bodyClassName}`}>{children}</div>
    </Tag>
  )
}
