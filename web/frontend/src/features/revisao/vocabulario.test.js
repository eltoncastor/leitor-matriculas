import { describe, it, expect } from "vitest";
import { rotuloCampo, corCampo, rotuloPendencia } from "./vocabulario";

describe("vocabulario", () => {
  it("rotuloCampo traduz os 5 campos conhecidos, mesmos nomes do Tkinter", () => {
    expect(rotuloCampo("data")).toBe("Data");
    expect(rotuloCampo("hora")).toBe("Hora");
    expect(rotuloCampo("matricula")).toBe("Matrícula");
    expect(rotuloCampo("motivo")).toBe("Motivo");
    expect(rotuloCampo("gestor")).toBe("Responsável");
  });

  it("rotuloCampo devolve o próprio nome para campo desconhecido -- nunca inventa rótulo", () => {
    expect(rotuloCampo("outro")).toBe("outro");
  });

  it("corCampo devolve uma cor por campo, e uma cor padrão para desconhecido", () => {
    expect(corCampo("data")).toMatch(/^#/);
    expect(corCampo("nao-existe")).toBe("#495057");
  });

  it("rotuloPendencia junta os campos bloqueantes por vírgula", () => {
    expect(rotuloPendencia(["data", "hora"])).toBe("Data, Hora");
    expect(rotuloPendencia(["matricula"])).toBe("Matrícula");
  });

  it("rotuloPendencia sem campo bloqueante nenhum cai em 'revisão'", () => {
    expect(rotuloPendencia([])).toBe("revisão");
    expect(rotuloPendencia(null)).toBe("revisão");
  });
});
