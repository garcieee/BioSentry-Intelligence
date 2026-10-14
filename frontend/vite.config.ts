import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The fixture provider imports data/synthetic/synthetic.json; serve the project and that
    // folder only (setting `allow` replaces Vite's default of the whole workspace root).
    fs: { allow: [".", "../data"] },
  },
})
