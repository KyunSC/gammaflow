import { JetBrains_Mono, Inter } from 'next/font/google'

// The backtester already ships these two; loading them on the board and the
// chart page too makes the three pages one product instead of two.
export const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v02-mono', display: 'swap' })
export const sans = Inter({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v02-sans', display: 'swap' })
export const fontVars = `${mono.variable} ${sans.variable}`
