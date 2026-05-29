"""
app/utils.py — Funções utilitárias compartilhadas pelo backend.
"""
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus


# ─── FUSO HORÁRIO ────────────────────────────────────────────────────────────
# Boa Vista - RR usa UTC-4 (Hora do Amazonas), sem horário de verão.
_BOA_VISTA = timezone(timedelta(hours=-4))


def agora() -> datetime:
    """Retorna o datetime atual no horário de Boa Vista - RR (UTC-4), sem tzinfo."""
    return datetime.now(_BOA_VISTA).replace(tzinfo=None)


# ─── GOOGLE MAPS ROTA ────────────────────────────────────────────────────────
def gerar_link_rota(entregas, cidade: str = "") -> str:
    """
    Gera um link de rota no Google Maps partindo SEMPRE da localização
    atual do entregador (GPS do celular), passando por todas as entregas
    na ordem da lista.

    Usa as colunas municipio e uf da própria entrega (quando disponíveis)
    para montar um endereço mais preciso no Maps.

    Formato usado: ?api=1 (query-string) com separador de waypoints
    pré-codificado como %7C (pipe literal).

    Por que %7C e não '|' direto?
        Se colocarmos '|' literal no href do HTML, alguns browsers mobile
        o re-encodam para '%7C' gerando '%257C' que o Maps não reconhece.
        Usando '%7C' já no href, o browser passa o valor intacto e o Maps
        recebe '%7C' → decodifica para '|' → separa as paradas corretamente.

    Por que query-string e não formato de caminho (/dir//stop1/stop2/)?
        No formato de caminho, '+' é tratado como caractere literal, não
        como espaço. Além disso, o '//' inicial é normalizado por proxies
        para '/' fazendo o Maps perder o segmento de origem. O formato
        query-string (?api=1) interpreta '+' como espaço corretamente.

    Omitir &origin= faz o Maps usar o GPS do celular automaticamente.

    Args:
        entregas: lista de objetos Entrega com atributos rua, numero, bairro,
                  e opcionalmente municipio, uf.
        cidade:   sufixo de fallback (usado quando entrega não tem municipio).

    Returns:
        URL completa do Google Maps, pronta para abrir no celular/desktop.
    """
    if not entregas:
        return ""

    def _encode(e) -> str:
        """Monta o endereço e codifica para query-string (espaços → '+')."""
        partes = [
            str(e.rua    or "").strip(),
            str(e.numero or "").strip(),
            str(e.bairro or "").strip(),
        ]
        # Usa municipio/uf da própria entrega (snapshot do Consinco)
        mun = getattr(e, "municipio", None) or ""
        uf  = getattr(e, "uf",        None) or ""
        if mun:
            partes.append(mun.strip())
        if uf:
            partes.append(uf.strip())
        elif not mun and cidade:
            # Fallback para cidade da filial quando não há municipio na entrega
            partes.append(cidade.strip())
        return quote_plus(" ".join(p for p in partes if p))

    encoded     = [_encode(e) for e in entregas]
    destination = encoded[-1]
    # %7C pré-codificado: browser não re-encoda, Maps recebe e decodifica para '|'
    waypoints   = "%7C".join(encoded[:-1])

    # origin omitido → Maps usa GPS do entregador automaticamente
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&destination={destination}"
    )
    if waypoints:
        url += f"&waypoints={waypoints}"
    url += "&travelmode=driving"

    return url
