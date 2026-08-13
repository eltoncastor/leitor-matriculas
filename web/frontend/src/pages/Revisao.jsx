import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, PartyPopper } from "lucide-react";
import GlassCard from "../components/ui/GlassCard";
import Button from "../components/ui/Button";
import { useRevisao } from "../features/revisao/useRevisao";
import ListaPendencias from "../features/revisao/ListaPendencias";
import FotoFolha from "../features/revisao/FotoFolha";
import FormularioRevisao from "../features/revisao/FormularioRevisao";
import { consultarListas, ApiError } from "../lib/api";

const CAMPOS_VAZIOS = { data: "", hora: "", matricula: "", motivo: "", gestor: "" };

/**
 * Rota `/lote/:loteId/revisao` -- Sub-fase 24c. Mesmo modelo mental da
 * Fase 21b no Tkinter: três áreas (pendências / foto / formulário), o
 * campo bloqueante em destaque, sugestões de contexto coladas a ele.
 * `useRevisao` é o único lugar com estado de navegação; esta página só
 * monta a tela e mantém os CAMPOS DIGITADOS localmente (nunca
 * pré-preenchidos com sugestão -- sempre reiniciados a partir do
 * registro quando a linha em foco muda, mesma garantia de `revisao_vars`
 * no Tkinter).
 */
export default function Revisao() {
  const { loteId } = useParams();
  const revisao = useRevisao(loteId);
  const [campos, setCampos] = useState(CAMPOS_VAZIOS);
  const [detalhesAbertos, setDetalhesAbertos] = useState(false);
  const [ultimoResultado, setUltimoResultado] = useState(null);
  const [listas, setListas] = useState(null);

  useEffect(() => {
    let cancelado = false;
    consultarListas(loteId)
      .then((dados) => {
        if (!cancelado) setListas(dados);
      })
      .catch(() => {
        // Listas são só sugestão (datalist) -- sem elas o campo continua
        // um texto livre normal, nunca bloqueia a revisão.
      });
    return () => {
      cancelado = true;
    };
  }, [loteId]);

  // Reinicia o formulário a cada troca do REGISTRO em foco -- NUNCA com
  // uma sugestão pré-preenchida, só com o valor já apurado do próprio
  // registro (mesma garantia testada na Fase 21b/18 do Tkinter). A
  // dependência é o OBJETO `registroAtual` (não só o índice) de
  // propósito: uma tentativa de confirmação que NÃO resolve (PROBLEMA D)
  // ainda assim pode ter normalizado algum campo no servidor (mesma
  // regra do Tkinter -- `_atualizar_painel_revisao` também é chamado no
  // caminho "ainda não confirmou"), e o formulário precisa refletir isso.
  // `ultimoResultado` (a mensagem de erro) é responsabilidade de
  // `onConfirmar`/dos handlers de navegação abaixo, não deste efeito --
  // senão a própria mensagem que acabamos de mostrar seria apagada no
  // mesmo instante (o confirm também troca a referência de `registroAtual`).
  useEffect(() => {
    if (!revisao.registroAtual) {
      setCampos(CAMPOS_VAZIOS);
      return;
    }
    const r = revisao.registroAtual;
    setCampos({
      data: r.data || "",
      hora: r.hora || "",
      matricula: r.matricula || "",
      motivo: r.motivo || "",
      gestor: r.gestor || "",
    });
    setDetalhesAbertos(false);
  }, [revisao.registroAtual]);

  const onCampoAlterado = useCallback((nome, valor) => {
    setCampos((atual) => ({ ...atual, [nome]: valor }));
  }, []);

  const onConfirmar = useCallback(async () => {
    setUltimoResultado(null);
    try {
      const resultado = await revisao.confirmar(campos);
      setUltimoResultado(resultado);
    } catch (e) {
      setUltimoResultado({
        confirmou_agora: false,
        observacao_classificacao: e instanceof ApiError ? e.detail : "Falha ao falar com o servidor.",
      });
    }
  }, [revisao, campos]);

  const onAnterior = useCallback(() => {
    setUltimoResultado(null);
    revisao.navegar(-1);
  }, [revisao]);

  const onProximo = useCallback(() => {
    setUltimoResultado(null);
    revisao.navegar(1);
  }, [revisao]);

  const onSelecionarPendencia = useCallback((posicao) => {
    setUltimoResultado(null);
    revisao.irPara(posicao);
  }, [revisao]);

  if (revisao.erro) {
    return <EstadoErro loteId={loteId} mensagem={revisao.erro} />;
  }

  if (revisao.carregando) {
    return <p className="text-center text-sm text-slate-400">Carregando pendências...</p>;
  }

  if (revisao.pendentes.length === 0) {
    return <EstadoTudoRevisado loteId={loteId} />;
  }

  const registro = revisao.registroAtual;
  const nomeDerivado = registro?.nome;
  const setorCargo = [registro?.setor, registro?.cargo].filter((v) => v && v !== "(não encontrado)").join(" · ");

  return (
    <div className="animate-fade-up flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">Revisão</h1>
          <p className="text-sm text-slate-500">Corrija os campos e confirme -- a validação decide, não o clique.</p>
        </div>
        <Button as={Link} to={`/lote/${loteId}`} variant="fantasma" size="sm" icon={ArrowLeft}>
          Voltar ao resultado
        </Button>
      </div>

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-[260px_1fr_420px]">
        <section className="flex min-h-0 min-w-0 flex-col">
          <h2 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
            Pendências ({revisao.pendentes.length})
          </h2>
          <GlassCard className="min-h-0 flex-1" padding="p-3">
            <ListaPendencias
              pendentes={revisao.pendentes}
              posicaoAtual={revisao.posicao}
              onSelecionar={onSelecionarPendencia}
            />
          </GlassCard>
        </section>

        <section className="flex min-h-0 min-w-0 flex-col">
          <h2 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Folha digitalizada</h2>
          <GlassCard className="min-h-0 min-w-0 flex-1" padding="p-3">
            <FotoFolha loteId={loteId} numeroPagina={registro?.pagina_origem} />
          </GlassCard>
        </section>

        <section className="flex min-h-0 min-w-0 flex-col">
          <h2 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Por que revisar / corrigir</h2>
          <GlassCard className="min-h-0 flex-1" padding="p-4">
            <FormularioRevisao
              valores={campos}
              onCampoAlterado={onCampoAlterado}
              explicacao={revisao.explicacao}
              detalhesAbertos={detalhesAbertos}
              onAlternarDetalhes={() => setDetalhesAbertos((v) => !v)}
              listas={listas}
              nome={nomeDerivado}
              setorCargo={setorCargo}
              posicaoTexto={`Pendente ${revisao.posicao + 1} de ${revisao.pendentes.length}`}
              progressoTexto={`${revisao.resolvidosSessao} de ${revisao.totalRevisados} revisados`}
              onAnterior={onAnterior}
              onProximo={onProximo}
              onConfirmar={onConfirmar}
              confirmando={revisao.confirmando}
              ultimoResultado={ultimoResultado}
            />
          </GlassCard>
        </section>
      </div>
    </div>
  );
}

function EstadoErro({ loteId, mensagem }) {
  return (
    <div className="mx-auto max-w-lg">
      <GlassCard className="space-y-3 text-center">
        <p className="text-sm text-rose-600">{mensagem}</p>
        <Button as={Link} to={`/lote/${loteId}`} variant="secundario" icon={ArrowLeft}>
          Voltar ao resultado
        </Button>
      </GlassCard>
    </div>
  );
}

function EstadoTudoRevisado({ loteId }) {
  return (
    <div className="animate-fade-up mx-auto max-w-lg">
      <GlassCard className="space-y-4 text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-3xl bg-emerald-50 text-emerald-600 ring-1 ring-emerald-600/10">
          <PartyPopper className="size-7" strokeWidth={1.75} />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">Nada pendente por aqui</h1>
          <p className="mt-1 text-sm text-slate-500">Todos os registros deste lote já foram confirmados.</p>
        </div>
        <Button as={Link} to={`/lote/${loteId}`} variant="secundario" icon={ArrowLeft}>
          Voltar ao resultado
        </Button>
      </GlassCard>
    </div>
  );
}
