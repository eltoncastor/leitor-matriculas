import { Routes, Route, useLocation } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import FluxoPrincipal from "./pages/FluxoPrincipal";
import PaginaLote from "./pages/PaginaLote";
import Revisao from "./pages/Revisao";

export default function App() {
  // A tela de Revisão (24c) precisa de mais largura que o fluxo
  // principal (três áreas lado a lado -- ver AppShell). `useLocation`
  // decide isso aqui, no único lugar que já sabe a rota atual, em vez de
  // cada página ter que se preocupar com a própria casca visual.
  const localizacao = useLocation();
  const telaLarga = localizacao.pathname.endsWith("/revisao");

  return (
    <AppShell largo={telaLarga}>
      <Routes>
        <Route path="/" element={<FluxoPrincipal />} />
        <Route path="/lote/:loteId" element={<PaginaLote />} />
        <Route path="/lote/:loteId/revisao" element={<Revisao />} />
      </Routes>
    </AppShell>
  );
}
