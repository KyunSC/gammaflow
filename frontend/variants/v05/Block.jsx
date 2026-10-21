'use client'

/**
 * Section shell for this design: a sentence-case heading on the same line as
 * its context (symbol, counts, legend) and the body under it. No border, no
 * title strip, no entrance animation; columns and sections are separated by
 * single hairlines in the layout instead.
 */
export default function Block({ title, meta, right, children, className = '', bodyClassName = '', id, headingLevel = 2 }) {
  const H = headingLevel === 3 ? 'h3' : 'h2'
  return (
    <section className={`v05-block ${className}`} id={id} aria-label={typeof title === 'string' ? title : undefined}>
      {title && (
        <header className="v05-h">
          <H>{title}</H>
          {meta && <span className="v05-meta">{meta}</span>}
          <span className="flex-1" />
          {right}
        </header>
      )}
      <div className={`v05-body ${bodyClassName}`}>{children}</div>
    </section>
  )
}

/** One line of text in the colour of what it reports. No box. */
export function Notice({ tone = 'neg', children }) {
  const color = tone === 'neg' ? 'text-neg' : tone === 'amber' ? 'text-amber' : 'text-muted'
  return (
    <div role={tone === 'neg' ? 'alert' : 'status'} className={`v05-rule-b flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 font-mono text-[11px] ${color}`}>
      {children}
    </div>
  )
}
