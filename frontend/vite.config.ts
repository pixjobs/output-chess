import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5500',
      '/move': 'http://127.0.0.1:5500',
      '/player-move': 'http://127.0.0.1:5500',
      '/status': 'http://127.0.0.1:5500',
      '/legal-moves': 'http://127.0.0.1:5500',
      '/reset': 'http://127.0.0.1:5500',
    },
  },
})
