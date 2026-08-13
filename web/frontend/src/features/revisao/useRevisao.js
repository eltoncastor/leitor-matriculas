import { useCallback, useEffect, useRef, useState } from "react";
import { confirmarRegistro, consultarExplicacao, consultarRegistros } from "../../lib/api";

/**
 * src/features/revisao/useRevisao.js
 *
 * Fase 24c: o "controlador" da tela de Revisão, equivalente em espírito a
 * `_atualizar_painel_revisao`/`_revisao_ir_para`/`_revisao_navegar`/
 * `_revisao_confirmar` no Tkinter (ver `ui/app.py`) -- MAS não decide
 * nada de negócio, só orquestra chamadas a `src/lib/api.js` e mantém o
 * estado de navegação local (posição atual, contador da sessão). Toda
 * decisão (o que é CONFIRMADO/REVISAO, o que bloqueia, o que sugerir)
 * vem pronta do backend.
 *
 * Pendentes são recalculados a partir de `registros` (status === "REVISAO")
 * a cada atualização -- nunca uma lista guardada à parte que possa
 * divergir, mesmo cuidado que `_indices_pendentes_revisao()` já tinha no
 * Tkinter ("a mesma fonte de verdade").
 */
export function useRevisao(loteId) {
  const [registros, setRegistros] = useState(null);
  const [posicao, setPosicao] = useState(0);
  const [resolvidosSessao, setResolvidosSessao] = useState(0);
  const [explicacao, setExplicacao] = useState(null);
  const [carregandoExplicacao, setCarregandoExplicacao] = useState(false);
  const [erro, setErro] = useState(null);
  const [confirmando, setConfirmando] = useState(false);
  // A posição atual pode mudar por navegação OU por uma pendência
  // desaparecer (foi confirmada) -- este ref evita pedir explicação de
  // uma posição que já não existe mais no meio de uma corrida de efeitos.
  const requisicaoExplicacaoEmAndamento = useRef(0);

  const carregarRegistros = useCallback(async () => {
    const dados = await consultarRegistros(loteId);
    setRegistros(dados);
    return dados;
  }, [loteId]);

  useEffect(() => {
    let cancelado = false;
    carregarRegistros().catch((e) => {
      if (!cancelado) setErro(e.message || String(e));
    });
    return () => {
      cancelado = true;
    };
  }, [carregarRegistros]);

  const pendentes = registros === null
    ? []
    : registros
        .map((registro, indice) => ({ registro, indice }))
        .filter((item) => item.registro.status === "REVISAO");

  const posicaoSegura = pendentes.length === 0 ? 0 : Math.min(posicao, pendentes.length - 1);
  const itemAtual = pendentes[posicaoSegura] || null;
  const indiceAtual = itemAtual ? itemAtual.indice : null;
  const registroAtual = itemAtual ? itemAtual.registro : null;

  // Busca a explicação sempre que o REGISTRO em foco muda (não a cada
  // render) -- mesmo gatilho de `_mostrar_explicacao_revisao`, chamado
  // de dentro de `_atualizar_painel_revisao` a cada troca de linha.
  useEffect(() => {
    if (indiceAtual === null || loteId == null) {
      setExplicacao(null);
      return;
    }
    const idRequisicao = ++requisicaoExplicacaoEmAndamento.current;
    setCarregandoExplicacao(true);
    consultarExplicacao(loteId, indiceAtual)
      .then((dados) => {
        if (requisicaoExplicacaoEmAndamento.current === idRequisicao) {
          setExplicacao(dados);
        }
      })
      .catch((e) => {
        if (requisicaoExplicacaoEmAndamento.current === idRequisicao) {
          setExplicacao(null);
          setErro(e.message || String(e));
        }
      })
      .finally(() => {
        if (requisicaoExplicacaoEmAndamento.current === idRequisicao) {
          setCarregandoExplicacao(false);
        }
      });
  }, [loteId, indiceAtual]);

  const irPara = useCallback((novaPosicao) => {
    setPosicao((atual) => {
      const total = pendentes.length;
      if (total === 0) return atual;
      return Math.max(0, Math.min(novaPosicao, total - 1));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendentes.length]);

  const navegar = useCallback((passo) => {
    setPosicao((atual) => {
      const total = pendentes.length;
      if (total === 0) return atual;
      return (atual + passo + total) % total;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendentes.length]);

  /**
   * Único caminho de confirmação: chama `POST .../confirmar` (que chama
   * `confirmar_revisao_manual` no backend) e nunca decide o resultado
   * aqui -- só reflete o que voltou. Devolve o corpo da resposta para o
   * chamador poder mostrar "ainda não é possível confirmar: ..." quando
   * `confirmou_agora` for falso (PROBLEMA D, Fase 7).
   */
  const confirmar = useCallback(async (campos) => {
    if (indiceAtual === null) return null;
    setConfirmando(true);
    try {
      const resultado = await confirmarRegistro(loteId, indiceAtual, campos);
      setRegistros((atual) => {
        const proximo = [...atual];
        proximo[indiceAtual] = { ...resultado.registro, campos_bloqueantes: atual[indiceAtual].campos_bloqueantes };
        return proximo;
      });
      if (resultado.confirmou_agora) {
        setResolvidosSessao((n) => n + 1);
        // A lista de pendentes encolheu -- a posição atual passa a
        // apontar pra próxima pendência sozinha (mesmo comportamento do
        // Tkinter: `_revisao_posicao` não muda, só o que ela aponta).
      }
      return resultado;
    } finally {
      setConfirmando(false);
    }
  }, [loteId, indiceAtual]);

  const totalRevisados = resolvidosSessao + pendentes.length;

  return {
    carregando: registros === null,
    erro,
    registros,
    pendentes,
    posicao: posicaoSegura,
    indiceAtual,
    registroAtual,
    explicacao,
    carregandoExplicacao,
    confirmando,
    resolvidosSessao,
    totalRevisados,
    irPara,
    navegar,
    confirmar,
    recarregar: carregarRegistros,
  };
}
