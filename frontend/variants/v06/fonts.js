import { IBM_Plex_Sans, JetBrains_Mono } from 'next/font/google'

// Plex Sans carries labels and prose; JetBrains Mono (already the terminal's
// number face) stays for figures, so every column of numbers lines up.
export const sans = IBM_Plex_Sans({ subsets: ['latin'], weight: ['400', '500', '600'], display: 'swap' })
export const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500'], display: 'swap' })

/** Inline style for a variant root: exposes both faces as custom properties
 *  so Tailwind's font-sans / font-mono (and our own CSS) pick them up. */
export const fontVars = {
  '--v06-sans': `${sans.style.fontFamily}, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
  '--v06-mono': `${mono.style.fontFamily}, ui-monospace, 'SF Mono', Menlo, monospace`,
  '--font-sans': `${sans.style.fontFamily}, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
  '--font-mono': `${mono.style.fontFamily}, ui-monospace, 'SF Mono', Menlo, monospace`,
}
