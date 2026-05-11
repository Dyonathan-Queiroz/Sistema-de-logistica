"""
app/utils.py — Funções utilitárias compartilhadas pelo backend.
"""
from urllib.parse import quote_plus


def gerar_link_rota(entregas, cidade: str = "") -> str:
    """
    Gera um link de rota no Google Maps partindo SEMPRE da localização
    atual do entregador (GPS do celular), passando por todas as entregas
    na ordem da lista.

    Usa o formato de CAMINHO (/maps/dir//stop1/stop2/…) em vez do formato
    de query-string (?api=1&waypoints=A|B), porque no mobile os browsers
    percent-encodam o separador '|' → '%7C', fazendo o Maps ignorar os
    waypoints intermediários e mostrar apenas o destino final.

    Formato gerado:
        https://www.google.com/maps/dir//<stop1>/<stop2>/…/<stopN>/

    O duplo '//' logo após 'dir' é interpretado pelo Google Maps como
    "usar localização atual (GPS)" como ponto de partida, sem precisar
    definir um origin fixo.

    Args:
        entregas: lista de objetos Entrega com atributos rua, numero e bairro.
        cidade:   sufixo adicionado a cada endereço (ex: "Boa Vista RR").

    Returns:
        URL completa do Google Maps, pronta para abrir no celular.

    Exemplo com 3 entregas em Boa Vista:
        https://www.google.com/maps/dir/
            /Rua+A+Centro+Boa+Vista+RR
            /Rua+B+Mecejana+Boa+Vista+RR
            /Rua+C+Asa+Branca+Boa+Vista+RR/
    """
    if not entregas:
        return ""

    def _encode(e) -> str:
        """Monta o endereço e codifica para URL (espaços → '+')."""
        partes = [
            str(e.rua    or "").strip(),
            str(e.numero or "").strip(),
            str(e.bairro or "").strip(),
        ]
        if cidade:
            partes.append(cidade.strip())
        return quote_plus(" ".join(p for p in partes if p))

    # Cada entrega vira um segmento de caminho — sem '|', sem encoding indevido
    stops = "/".join(_encode(e) for e in entregas)

    # Duplo '//' = GPS como origem; barra final = boa prática p/ o Maps app
    return f"https://www.google.com/maps/dir//{stops}/"
