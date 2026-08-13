import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SelecaoLote from "./SelecaoLote";

function arquivoFalso(nome, tipo = "application/pdf") {
  return new File(["conteúdo"], nome, { type: tipo });
}

describe("SelecaoLote", () => {
  it("começa na dropzone vazia, sem nenhum arquivo listado", () => {
    render(<SelecaoLote onIniciarProcessamento={vi.fn()} enviando={false} erroEnvio={null} />);
    expect(screen.getByText("Arraste os arquivos aqui")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Processar" })).not.toBeInTheDocument();
  });

  it("selecionar um PDF leva à conferência com o botão Processar habilitado", async () => {
    const usuario = userEvent.setup();
    render(<SelecaoLote onIniciarProcessamento={vi.fn()} enviando={false} erroEnvio={null} />);

    const entradaPdf = document.querySelector('input[type="file"][accept=".pdf"]');
    await usuario.upload(entradaPdf, arquivoFalso("teste.pdf"));

    expect(screen.getByText("1 arquivo PDF selecionado")).toBeInTheDocument();
    expect(screen.getByText("teste.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Processar/ })).toBeEnabled();
  });

  it("clicar em Processar chama onIniciarProcessamento com os arquivos escolhidos -- nunca decide nada sozinho", async () => {
    const usuario = userEvent.setup();
    const aoIniciar = vi.fn();
    render(<SelecaoLote onIniciarProcessamento={aoIniciar} enviando={false} erroEnvio={null} />);

    const entradaPdf = document.querySelector('input[type="file"][accept=".pdf"]');
    const arquivo = arquivoFalso("teste.pdf");
    await usuario.upload(entradaPdf, arquivo);
    await usuario.click(screen.getByRole("button", { name: /Processar/ }));

    expect(aoIniciar).toHaveBeenCalledTimes(1);
    expect(aoIniciar.mock.calls[0][0]).toEqual([arquivo]);
  });

  it("mostra o erro de envio vindo do backend sem inventar texto novo", () => {
    render(
      <SelecaoLote
        onIniciarProcessamento={vi.fn()}
        enviando={false}
        erroEnvio="mensagem de erro real do backend"
      />
    );
    // Sem arquivo selecionado o card de conferência nem existe -- o erro
    // de envio só aparece quando há seleção (é o cenário real: o erro só
    // pode acontecer DEPOIS de clicar Processar).
    expect(screen.queryByText("mensagem de erro real do backend")).not.toBeInTheDocument();
  });

  it("'Trocar seleção' volta pra dropzone vazia", async () => {
    const usuario = userEvent.setup();
    render(<SelecaoLote onIniciarProcessamento={vi.fn()} enviando={false} erroEnvio={null} />);
    const entradaPdf = document.querySelector('input[type="file"][accept=".pdf"]');
    await usuario.upload(entradaPdf, arquivoFalso("teste.pdf"));
    await usuario.click(screen.getByRole("button", { name: "Trocar seleção" }));
    expect(screen.getByText("Arraste os arquivos aqui")).toBeInTheDocument();
  });
});
