import { Inter, JetBrains_Mono } from 'next/font/google'

// Same two faces the backtester already ships, so the dashboard and chart
// pages stop reading as a different product. next/font serves them locally.
export const sans = Inter({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--v4-font-sans', display: 'swap' })
export const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500'], variable: '--v4-font-mono', display: 'swap' })
export const fontVars = `${sans.variable} ${mono.variable}`
