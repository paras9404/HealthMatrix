import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Force-prebundle react-helmet-async + its CJS-only react-fast-compare dep, otherwise
  // Vite's ESM dev pipeline fails to resolve a "default" export and Helmet silently
  // never applies SEO tags in development.
  optimizeDeps: {
    include: ['react-helmet-async', 'react-fast-compare'],
  },
  server: {
    port: Number(process.env.PORT) || 5173,
    host: true,
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app', '.ngrok.io', '.loca.lt'],
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:5001',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
})
