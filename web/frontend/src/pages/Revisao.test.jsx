import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Revisao from "./Revisao";
import * as api from "../lib/api";

vi.mock("../lib/api", () => ({
  consultarRegistros: vi.fn(),
  consultarExplicacao: vi.fn(),
  consultarListas: vi.fn(),
  confirmarRegistro: vi.fn(),
  urlImagemPagina: vi.fn(() => "http://teste/imagem.jpg"),
  ApiError: class ApiError extends Error {},
}));

function renderNaRota() {
  return render(
    <MemoryRouter initialEntries={["/lote/lote-1/revisao"]}>
      <Routes>
        <Route path="/lote/:loteId/revisao" element={<Revisao />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.consultarListas.mockResolvedValue({ motivos: [], gestores: [] });
  api.consultarExplicacao.mockResolvedValue({
    explicacao: {
      campos_bloqueantes: ["matricula"],
      titulo: "A dúvida está em: Matrícula",
      detalhes: ["Matrícula: o OCR leu '999X9' nesta coluna"],
      por_campo: {},
    },
    sinais_contexto: [],
  });
});

describe("Revisao (tela) -- segurança da revisão manual", () => {
  it("nunca pré-preenche um campo com sugestão -- o formulário só reflete o que já está no registro", async () => {
    api.consultarRegistros.mockResolvedValue([
      {
        status: "REVISAO", pagina_origem: 1, matricula: "", data: "23/04/26", hora: "",
        motivo: "RH", gestor: "", nome: "", setor: "", cargo: "",
        campos_bloqueantes: ["matricula"],
      },
    ]);
    renderNaRota();

    await waitFor(() => expect(screen.getByDisplayValue("23/04/26")).toBeInTheDocument());
    // O campo Matrícula está VAZIO no registro -- tem que continuar vazio
    // no formulário, mesmo com a explicação carregada e apontando o
    // problema. Nenhuma sugestão pode ir parar dentro do <input>.
    const campoMatricula = screen.getByLabelText(/Matrícula/i);
    expect(campoMatricula.value).toBe("");
  });

  it("o botão 'Confirmar e próximo' existe mas NUNCA é chamado sozinho -- confirmarRegistro só dispara com clique explícito", async () => {
    api.consultarRegistros.mockResolvedValue([
      { status: "REVISAO", pagina_origem: 1, matricula: "111", data: "", hora: "", motivo: "", gestor: "", nome: "", setor: "", cargo: "", campos_bloqueantes: ["data"] },
      { status: "REVISAO", pagina_origem: 2, matricula: "222", data: "", hora: "", motivo: "", gestor: "", nome: "", setor: "", cargo: "", campos_bloqueantes: ["data"] },
    ]);
    renderNaRota();

    await waitFor(() => expect(screen.getByText(/Pendente 1 de 2/)).toBeInTheDocument());
    // Navegar entre pendências (Próximo) não deve, sozinho, confirmar nada.
    screen.getByRole("button", { name: "Próximo" }).click();
    await waitFor(() => expect(screen.getByText(/Pendente 2 de 2/)).toBeInTheDocument());

    expect(api.confirmarRegistro).not.toHaveBeenCalled();
  });
});
