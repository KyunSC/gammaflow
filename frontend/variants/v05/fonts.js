import { JetBrains_Mono, Inter } from 'next/font/google'

// Same faces the backtester already loads, so the dashboard and chart page
// read as the same product. next/font self-hosts them at build time.
export const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v05-mono', display: 'swap' })
export const sans = Inter({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v05-sans', display: 'swap' })
export const fontVars = `${mono.variable} ${sans.variable}`
