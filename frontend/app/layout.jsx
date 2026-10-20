import './globals.css'
import '../variants/badge.css'
import { UiVariantProvider } from '../variants/UiVariant'
import { SpeedInsights } from "@vercel/speed-insights/next"
import { Analytics } from "@vercel/analytics/next"

export const metadata = {
  title: 'Market Data Dashboard',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body><UiVariantProvider>{children}</UiVariantProvider><SpeedInsights /><Analytics /></body>
    </html>
  )
}
