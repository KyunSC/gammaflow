import './globals.css'
import { SpeedInsights } from "@vercel/speed-insights/next"
import { Analytics } from "@vercel/analytics/next"
import SyntheticDataNotice from '../components/SyntheticDataNotice'

export const metadata = {
  title: 'Market Data Dashboard',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}<SyntheticDataNotice /><SpeedInsights /><Analytics /></body>
    </html>
  )
}
