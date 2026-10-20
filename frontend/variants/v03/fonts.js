import { JetBrains_Mono, Inter } from 'next/font/google'

// Same families the backtester already ships, loaded once more under this
// design's own variables so / and /ticker get them too (next/font dedupes files).
export const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--v3-font-mono',
  display: 'swap',
})

export const sans = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--v3-font-sans',
  display: 'swap',
})

export const fontVars = `${mono.variable} ${sans.variable}`
