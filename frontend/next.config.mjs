import { resolveDataSource } from './lib/dataSource.mjs'

// 'synthetic' unless GAMMAFLOW_DATA=real on a local machine (see lib/dataSource.mjs).
const dataSource = resolveDataSource()
const apiUrl = process.env.API_URL || 'https://azure-market-data.onrender.com'

/** @type {import('next').NextConfig} */
const nextConfig = {
  env: { GF_DATA_SOURCE: dataSource },
  async rewrites() {
    // Synthetic builds answer /api/* from app/api/** and never reach the backend.
    if (dataSource !== 'real') return []
    // beforeFiles so the proxy wins over those synthetic route handlers.
    return {
      beforeFiles: [
        { source: '/api/backtest/:path*', destination: `${apiUrl}/api/backtest/:path*` },
        // Match subpaths too (e.g. /api/market/live, /api/historical/since).
        { source: '/api/market/:path+', destination: `${apiUrl}/api/market/:path+` },
        { source: '/api/market', destination: `${apiUrl}/api/market` },
        { source: '/api/historical/:path+', destination: `${apiUrl}/api/historical/:path+` },
        { source: '/api/historical', destination: `${apiUrl}/api/historical` },
        { source: '/api/gamma', destination: `${apiUrl}/api/gamma` },
        { source: '/api/volume-profile/:path+', destination: `${apiUrl}/api/volume-profile/:path+` },
      ],
    }
  },
}

export default nextConfig
