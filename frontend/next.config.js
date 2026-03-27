/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  distDir: 'dist',
  assetPrefix: '/',
  images: {
    unoptimized: true,
  },
  trailingSlash: true,
}

module.exports = nextConfig
