import { useCallback, useRef, useState } from "react";
import { UploadCloud, FileText, Image as ImageIcon, X, ArrowRight, AlertCircle } from "lucide-react";
import GlassCard from "../../components/ui/GlassCard";
import Button from "../../components/ui/Button";
import { classificarSelecao, formatarTamanho, EXTENSOES_IMAGEM } from "./regrasArquivo";

/**
 * Tela 1+2 do fluxo (Fase 21a no Tkinter: "Escolher folhas" -> "Conferir a
 * seleção"): dropzone vazia até o operador escolher arquivos; depois vira
 * a lista de conferência com o botão "Processar" -- as DUAS telas do
 * pedido da fase moram no mesmo componente porque a transição entre elas
 * é só estado local (nenhuma chamada de rede acontece até "Processar").
 */
export default function SelecaoLote({ onIniciarProcessamento, enviando, erroEnvio }) {
  const [arquivos, setArquivos] = useState([]);
  const [erroSelecao, setErroSelecao] = useState(null);
  const [arrastando, setArrastando] = useState(false);
  const inputImagensRef = useRef(null);
  const inputPdfRef = useRef(null);

  const aplicarSelecao = useCallback((listaArquivos) => {
    const arr = Array.from(listaArquivos);
    const { tipo, erro } = classificarSelecao(arr);
    if (erro) {
      setErroSelecao(erro);
      return;
    }
    setErroSelecao(null);
    setArquivos(tipo ? arr : []);
  }, []);

  const removerArquivo = (indice) => {
    setArquivos((atual) => {
      const proximo = atual.filter((_, i) => i !== indice);
      // Sem arquivos sobrando, volta pra dropzone vazia.
      return proximo;
    });
  };

  const limparSelecao = () => {
    setArquivos([]);
    setErroSelecao(null);
  };

  const onDrop = (evento) => {
    evento.preventDefault();
    setArrastando(false);
    aplicarSelecao(evento.dataTransfer.files);
  };

  const temSelecao = arquivos.length > 0;
  const tipoSelecao = temSelecao ? classificarSelecao(arquivos).tipo : null;

  return (
    <div className="animate-fade-up space-y-6">
      <div className="space-y-1.5 text-center sm:text-left">
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 sm:text-4xl">
          Ler as folhas de liberação
        </h1>
        <p className="text-base text-slate-600">
          Envie as fotos das folhas ou o PDF do mês -- o reconhecimento do texto manuscrito começa
          só depois de você conferir a seleção.
        </p>
      </div>

      {!temSelecao ? (
        <GlassCard padding="p-0" className="overflow-hidden">
          <div
            onDragOver={(e) => { e.preventDefault(); setArrastando(true); }}
            onDragLeave={() => setArrastando(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center gap-4 border-2 border-dashed p-12 text-center transition-colors duration-200 sm:p-16 ${
              arrastando ? "border-brand-400 bg-brand-50/60" : "border-transparent"
            }`}
          >
            <div className="flex size-16 items-center justify-center rounded-3xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
              <UploadCloud className="size-8" strokeWidth={1.75} />
            </div>
            <div className="space-y-1">
              <p className="text-lg font-semibold text-slate-800">Arraste os arquivos aqui</p>
              <p className="text-sm text-slate-500">ou escolha um jeito abaixo</p>
            </div>
            <div className="flex flex-wrap justify-center gap-3 pt-2">
              <Button
                variant="primario"
                icon={ImageIcon}
                onClick={() => inputImagensRef.current?.click()}
              >
                Escolher fotos
              </Button>
              <Button
                variant="secundario"
                icon={FileText}
                onClick={() => inputPdfRef.current?.click()}
              >
                Escolher PDF do mês
              </Button>
            </div>
            <p className="pt-1 text-xs text-slate-400">
              Formatos aceitos: {EXTENSOES_IMAGEM.join(", ")} (uma ou mais fotos) ou um único PDF
            </p>
            <input
              ref={inputImagensRef}
              type="file"
              accept={EXTENSOES_IMAGEM.join(",")}
              multiple
              className="hidden"
              onChange={(e) => aplicarSelecao(e.target.files)}
            />
            <input
              ref={inputPdfRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => aplicarSelecao(e.target.files)}
            />
          </div>
        </GlassCard>
      ) : (
        <GlassCard className="animate-fade-up space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">
                Conferência
              </p>
              <h2 className="text-xl font-bold text-slate-900">
                {tipoSelecao === "pdf"
                  ? "1 arquivo PDF selecionado"
                  : `${arquivos.length} ${arquivos.length === 1 ? "foto selecionada" : "fotos selecionadas"}`}
              </h2>
            </div>
            <Button variant="fantasma" size="sm" onClick={limparSelecao}>
              Trocar seleção
            </Button>
          </div>

          <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {arquivos.map((arquivo, indice) => (
              <li
                key={`${arquivo.name}-${indice}`}
                className="flex items-center gap-3 rounded-2xl bg-white/70 px-4 py-2.5 ring-1 ring-slate-900/5"
              >
                {tipoSelecao === "pdf" ? (
                  <FileText className="size-5 shrink-0 text-brand-500" strokeWidth={1.75} />
                ) : (
                  <ImageIcon className="size-5 shrink-0 text-brand-500" strokeWidth={1.75} />
                )}
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-700">
                  {arquivo.name}
                </span>
                <span className="shrink-0 text-xs text-slate-400">{formatarTamanho(arquivo.size)}</span>
                <button
                  type="button"
                  onClick={() => removerArquivo(indice)}
                  className="shrink-0 rounded-full p-1 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500"
                  aria-label={`Remover ${arquivo.name}`}
                >
                  <X className="size-4" />
                </button>
              </li>
            ))}
          </ul>

          {erroEnvio ? (
            <div className="flex items-start gap-2 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-rose-600/10">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span>{erroEnvio}</span>
            </div>
          ) : null}

          <div className="flex justify-end">
            <Button
              variant="primario"
              size="lg"
              iconRight={ArrowRight}
              disabled={enviando || arquivos.length === 0}
              onClick={() => onIniciarProcessamento(arquivos)}
            >
              {enviando ? "Enviando..." : "Processar"}
            </Button>
          </div>
        </GlassCard>
      )}

      {erroSelecao ? (
        <div className="flex animate-fade-in items-start gap-2 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-rose-600/10">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{erroSelecao}</span>
        </div>
      ) : null}
    </div>
  );
}
