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
    // Ajuste pontual pós-Fase 24 (acesso remoto via Tailscale -- ver
    // CLAUDE.md e saida/ajuste_acesso_tailscale.md): por padrão o dev
    // server do Vite só aceita conexões vindas da própria máquina
    // (bind em 127.0.0.1). `host: true` faz o Vite escutar em todas as
    // interfaces de rede (equivalente a 0.0.0.0), então um outro
    // dispositivo na mesma tailnet (ou na mesma rede local) consegue
    // abrir http://<IP-desta-máquina>:5173. O proxy abaixo continua
    // apontando para 127.0.0.1:8000 -- o backend roda na MESMA máquina
    // que o Vite, então o proxy nunca precisa sair dela; é só a conexão
    // do NAVEGADOR remoto até este dev server que passa a ser aceita.
    host: true,
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
