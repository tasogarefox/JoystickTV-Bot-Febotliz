import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import { resolve } from "path"

// Adjust these values to match your server
const baseURL = '/app/'
const host = 'localhost'
const port = 29392

// https://vite.dev/config/
export default defineConfig({
  base: baseURL,
  plugins: [
    vue(),
    vueDevTools(),
  ],
  build: {
    rollupOptions: {
      input: {
        dashboard: resolve(__dirname, "index.html"),
        overlay_vibegraph: resolve(__dirname, "overlay/vibegraph/index.html"),
        config_vibegraph: resolve(__dirname, "overlay/vibegraph/config/index.html"),
      },
    },
  },
  resolve: {
    extensions: ['.js', '.ts', '.vue'],
    alias: {
      '@': fileURLToPath(new URL('src', import.meta.url)),
    },
  },
  server: {
    open: false, // Automatically open the app in the browser on start
    proxy: {
      '/static': `http://${host}:${port}`,
      '/icon': `http://${host}:${port}`,
      '/api': `http://${host}:${port}`,
      '/ws': {
        target: `ws://${host}:${port}`,
        ws: true,
        changeOrigin: true,
      },
      '/jstv': `http://${host}:${port}`,
    },
  },
})
