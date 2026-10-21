import { JetBrains_Mono, Inter } from 'next/font/google'

// Same faces the backtester already ships, loaded here too so the dashboard and
// ticker pages of this design speak the same type as /backtest.
export const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v9-mono', display: 'swap' })
export const sans = Inter({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v9-sans', display: 'swap' })
export const fontVars = `${mono.variable} ${sans.variable}`
