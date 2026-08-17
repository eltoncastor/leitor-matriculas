import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'

// Ajuste pontual pós-Fase 25 (deploy atrás de sub-path, ver CLAUDE.md e
// saida/ajuste_subpath_leitor.md): `basename` deriva da mesma
// `import.meta.env.BASE_URL` que `src/lib/api.js` usa para a base da API
// -- nunca hardcoded aqui. Em dev e no build padrão (desktop/`.exe`),
// `BASE_URL` é "/" e o resultado é "/" (equivalente a omitir `basename`,
// o comportamento de sempre). Só o build da VPS (`VITE_BASE_PATH=/leitor/`)
// produz "/leitor".
const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
