import { Inter, JetBrains_Mono } from 'next/font/google'

// Same two faces as /backtest, now on every page: Inter for words, JetBrains
// Mono for numbers and data.
export const sans = Inter({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v01-sans', display: 'swap' })
export const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v01-mono', display: 'swap' })
export const fontVars = `${sans.variable} ${mono.variable}`
