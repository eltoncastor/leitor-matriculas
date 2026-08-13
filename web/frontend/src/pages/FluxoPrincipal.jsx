import { useState } from "react";
import { useNavigate } from "react-router-dom";
import SelecaoLote from "../features/lote/SelecaoLote";
import { criarLote, dispararProcessamento, ApiError } from "../lib/api";

/**
 * Página inicial (`/`): escolher arquivos -> conferir -> processar. Só
 * decide NAVEGAÇÃO e ORQUESTRA as duas chamadas de API (criar lote,
 * disparar processamento) -- a decisão de negócio (o que é um lote
 * válido, como o processamento roda) já é toda do backend.
 */
export default function FluxoPrincipal() {
  const [enviando, setEnviando] = useState(false);
  const [erroEnvio, setErroEnvio] = useState(null);
  const navigate = useNavigate();

  const iniciarProcessamento = async (arquivos) => {
    setEnviando(true);
    setErroEnvio(null);
    try {
      const lote = await criarLote(arquivos);
      await dispararProcessamento(lote.lote_id);
      navigate(`/lote/${lote.lote_id}`);
    } catch (erro) {
      setErroEnvio(
        erro instanceof ApiError
          ? erro.detail
          : "Não foi possível falar com o servidor -- confira se o backend está rodando."
      );
      setEnviando(false);
    }
  };

  return (
    <SelecaoLote
      onIniciarProcessamento={iniciarProcessamento}
      enviando={enviando}
      erroEnvio={erroEnvio}
    />
  );
}
