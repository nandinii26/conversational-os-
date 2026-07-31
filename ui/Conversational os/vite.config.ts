import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  // Use './' for Electron (relative asset paths) and '/' for Vercel web deployment
  base: process.env.VITE_ELECTRON === '1' ? './' : '/',
})