import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useRevisao } from "./useRevisao";
import * as api from "../../lib/api";

vi.mock("../../lib/api", () => ({
  consultarRegistros: vi.fn(),
  consultarExplicacao: vi.fn(),
  confirmarRegistro: vi.fn(),
}));

function registro(status, extra = {}) {
  return { status, data: "", hora: "", matricula: "", motivo: "", gestor: "", pagina_origem: 1, ...extra };
}

const EXPLICACAO_VAZIA = {
  explicacao: { campos_bloqueantes: [], titulo: "", detalhes: [], por_campo: {} },
  sinais_contexto: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.consultarExplicacao.mockResolvedValue(EXPLICACAO_VAZIA);
});

describe("useRevisao -- navegação", () => {
  it("calcula pendentes só a partir de registros com status REVISAO", async () => {
    api.consultarRegistros.mockResolvedValue([
      registro("CONFIRMADO"),
      registro("REVISAO", { matricula: "111" }),
      registro("ERRO"),
      registro("REVISAO", { matricula: "222" }),
    ]);
    const { result } = renderHook(() => useRevisao("lote-1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));

    expect(result.current.pendentes).toHaveLength(2);
    expect(result.current.pendentes.map((p) => p.indice)).toEqual([1, 3]);
    expect(result.current.registroAtual.matricula).toBe("111");
  });

  it("navegar(1) avança e dá a volta (circular), navegar(-1) volta e dá a volta", async () => {
    api.consultarRegistros.mockResolvedValue([
      registro("REVISAO", { matricula: "A" }),
      registro("REVISAO", { matricula: "B" }),
      registro("REVISAO", { matricula: "C" }),
    ]);
    const { result } = renderHook(() => useRevisao("lote-1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));

    expect(result.current.registroAtual.matricula).toBe("A");
    act(() => result.current.navegar(1));
    await waitFor(() => expect(result.current.registroAtual.matricula).toBe("B"));
    act(() => result.current.navegar(1));
    await waitFor(() => expect(result.current.registroAtual.matricula).toBe("C"));
    // do último volta pro primeiro (circular)
    act(() => result.current.navegar(1));
    await waitFor(() => expect(result.current.registroAtual.matricula).toBe("A"));
    // do primeiro, "anterior" vai pro último (circular na outra direção)
    act(() => result.current.navegar(-1));
    await waitFor(() => expect(result.current.registroAtual.matricula).toBe("C"));
  });

  it("irPara(n) vai direto pra posição pedida (clicar na lista de pendências)", async () => {
    api.consultarRegistros.mockResolvedValue([
      registro("REVISAO", { matricula: "A" }),
      registro("REVISAO", { matricula: "B" }),
      registro("REVISAO", { matricula: "C" }),
    ]);
    const { result } = renderHook(() => useRevisao("lote-1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));

    act(() => result.current.irPara(2));
    await waitFor(() => expect(result.current.registroAtual.matricula).toBe("C"));
  });

  it("irPara com posição fora do intervalo é limitada (nunca quebra)", async () => {
    api.consultarRegistros.mockResolvedValue([
      registro("REVISAO", { matricula: "A" }),
      registro("REVISAO", { matricula: "B" }),
    ]);
    const { result } = renderHook(() => useRevisao("lote-1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));

    act(() => result.current.irPara(99));
    await waitFor(() => expect(result.current.registroAtual.matricula).toBe("B"));
  });
});

describe("useRevisao -- confirmação (nunca automática)", () => {
  it("carregar/navegar NUNCA chama confirmarRegistro sozinho", async () => {
    api.consultarRegistros.mockResolvedValue([registro("REVISAO", { matricula: "A" })]);
    const { result } = renderHook(() => useRevisao("lote-1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));
    act(() => result.current.navegar(1));
    act(() => result.current.irPara(0));

    expect(api.confirmarRegistro).not.toHaveBeenCalled();
  });

  it("confirmar() é a ÚNICA forma de mudar o status -- chama a API com o índice certo e os campos exatos digitados", async () => {
    api.consultarRegistros.mockResolvedValue([
      registro("REVISAO", { matricula: "111" }),
      registro("REVISAO", { matricula: "222" }),
    ]);
    api.confirmarRegistro.mockResolvedValue({
      registro: { ...registro("CONFIRMADO", { matricula: "111" }) },
      status_anterior: "REVISAO",
      confirmou_agora: true,
      observacao_classificacao: "",
    });
    const { result } = renderHook(() => useRevisao("lote-1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));

    const campos = { data: "23/04/26", hora: "", matricula: "111", motivo: "RH", gestor: "X" };
    await act(async () => {
      await result.current.confirmar(campos);
    });

    expect(api.confirmarRegistro).toHaveBeenCalledTimes(1);
    expect(api.confirmarRegistro).toHaveBeenCalledWith("lote-1", 0, campos);
    // a pendência resolvida sai da lista -- sobra só a segunda
    expect(result.current.pendentes).toHaveLength(1);
    expect(result.current.resolvidosSessao).toBe(1);
  });

  it("confirmar() que NÃO resolve (confirmou_agora=false) mantém a linha pendente e não mexe no contador", async () => {
    api.consultarRegistros.mockResolvedValue([registro("REVISAO", { matricula: "111" })]);
    api.confirmarRegistro.mockResolvedValue({
      registro: { ...registro("REVISAO", { matricula: "111" }) },
      status_anterior: "REVISAO",
      confirmou_agora: false,
      observacao_classificacao: "matrícula não encontrada",
    });
    const { result } = renderHook(() => useRevisao("lote-1"));
    await waitFor(() => expect(result.current.carregando).toBe(false));

    let resultado;
    await act(async () => {
      resultado = await result.current.confirmar({ data: "", hora: "", matricula: "", motivo: "", gestor: "" });
    });

    expect(resultado.confirmou_agora).toBe(false);
    expect(result.current.pendentes).toHaveLength(1);
    expect(result.current.resolvidosSessao).toBe(0);
  });
});
