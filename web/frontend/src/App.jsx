import { Routes, Route } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import FluxoPrincipal from "./pages/FluxoPrincipal";
import PaginaLote from "./pages/PaginaLote";
import RevisaoPlaceholder from "./pages/RevisaoPlaceholder";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<FluxoPrincipal />} />
        <Route path="/lote/:loteId" element={<PaginaLote />} />
        <Route path="/lote/:loteId/revisao" element={<RevisaoPlaceholder />} />
      </Routes>
    </AppShell>
  );
}
