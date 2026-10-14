import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The fixture provider imports data/synthetic/synthetic.json from the repo root.
    fs: { allow: [".."] },
  },
})
