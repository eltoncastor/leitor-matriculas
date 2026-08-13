import { describe, it, expect } from "vitest";
import { classificarSelecao, formatarTamanho } from "./regrasArquivo";

function arquivoFalso(nome, tamanho = 1024) {
  return new File([new Uint8Array(tamanho)], nome);
}

describe("classificarSelecao", () => {
  it("aceita 1 único PDF", () => {
    const { tipo, erro } = classificarSelecao([arquivoFalso("teste.pdf")]);
    expect(tipo).toBe("pdf");
    expect(erro).toBeNull();
  });

  it("aceita 1 ou mais imagens", () => {
    const { tipo, erro } = classificarSelecao([arquivoFalso("a.jpg"), arquivoFalso("b.png")]);
    expect(tipo).toBe("imagens");
    expect(erro).toBeNull();
  });

  it("recusa 2 PDFs juntos", () => {
    const { tipo, erro } = classificarSelecao([arquivoFalso("a.pdf"), arquivoFalso("b.pdf")]);
    expect(tipo).toBeNull();
    expect(erro).toMatch(/sozinho/);
  });

  it("recusa misturar PDF com imagem", () => {
    const { tipo, erro } = classificarSelecao([arquivoFalso("a.pdf"), arquivoFalso("b.jpg")]);
    expect(tipo).toBeNull();
    expect(erro).toMatch(/sozinho/);
  });

  it("recusa extensão não suportada", () => {
    const { tipo, erro } = classificarSelecao([arquivoFalso("nota.txt")]);
    expect(tipo).toBeNull();
    expect(erro).toMatch(/Formato não aceito/);
  });

  it("seleção vazia não é erro nem tipo -- estado neutro", () => {
    const { tipo, erro } = classificarSelecao([]);
    expect(tipo).toBeNull();
    expect(erro).toBeNull();
  });
});

describe("formatarTamanho", () => {
  it("bytes pequenos ficam em B", () => {
    expect(formatarTamanho(500)).toBe("500 B");
  });
  it("na casa dos milhares vira KB", () => {
    expect(formatarTamanho(2048)).toBe("2 KB");
  });
  it("na casa dos milhões vira MB", () => {
    expect(formatarTamanho(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});
