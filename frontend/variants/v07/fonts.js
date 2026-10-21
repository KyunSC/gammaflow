import { JetBrains_Mono, Inter } from 'next/font/google'

// Same faces as /backtest, loaded here too so the dashboard and ticker pages
// share the backtester's type instead of the system stack.
export const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--v7-font-mono',
  display: 'swap',
})

export const sans = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--v7-font-sans',
  display: 'swap',
})

export const fontVars = `${mono.variable} ${sans.variable}`
