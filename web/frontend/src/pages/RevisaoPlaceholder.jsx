import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Hammer } from "lucide-react";
import GlassCard from "../components/ui/GlassCard";
import Button from "../components/ui/Button";

/**
 * Placeholder da tela de Revisão (Sub-fase 24c, ainda não implementada).
 * Existe só para o botão "Revisar pendências" da tela de Resultado ter um
 * destino navegável de ponta a ponta, como pedido no escopo da 24b -- a
 * tela DE VERDADE (foto da folha, formulário, explicação da Fase 18)
 * ainda não deve ser construída aqui.
 */
export default function RevisaoPlaceholder() {
  const { loteId } = useParams();
  return (
    <div className="animate-fade-up mx-auto max-w-lg">
      <GlassCard className="space-y-4 text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-3xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
          <Hammer className="size-7" strokeWidth={1.75} />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">Revisão -- em construção</h1>
          <p className="mt-1 text-sm text-slate-500">
            A tela de revisão (foto da folha, explicação de por que cada linha ficou pendente,
            correção manual) é a Sub-fase 24c. Este é só o destino provisório para o fluxo
            principal ser navegável de ponta a ponta.
          </p>
          <p className="mt-3 font-mono text-xs text-slate-400">lote_id: {loteId}</p>
        </div>
        <Button as={Link} to={`/lote/${loteId}`} variant="secundario" icon={ArrowLeft}>
          Voltar ao resultado
        </Button>
      </GlassCard>
    </div>
  );
}
