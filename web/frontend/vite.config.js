import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Fase 24b: o frontend nunca fala com o backend por porta fixa espalhada
// pelo código -- toda chamada de API usa o prefixo `/api` (ver
// src/lib/api.js), e é o proxy do Vite abaixo que resolve isso para o
// FastAPI real em desenvolvimento (`web/backend/main.py`, 127.0.0.1:8000).
// `rewrite` remove o prefixo antes de encaminhar, porque as rotas do
// backend continuam em `/lotes`, `/saude`, sem `/api` -- criar esse
// prefixo só no backend também seria válido, mas mudaria o contrato que a
// Sub-fase 24a já commitou, e o pedido desta sub-fase é ajuste de
// contrato só quando necessário.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    globals: true,
  },
})
