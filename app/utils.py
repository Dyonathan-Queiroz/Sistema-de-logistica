"""
app/utils.py — Funções utilitárias compartilhadas pelo backend.
"""
from urllib.parse import quote_plus


def gerar_link_rota(entregas, cidade: str = "") -> str:
    """
    Gera um link de rota no Google Maps partindo SEMPRE da localização
    atual do entregador (GPS do celular).

    Regras:
        - 0 entregas  → retorna ""
        - 1 entrega   → GPS → entrega1
        - 2+ entregas → GPS → entrega1 → entrega2 → … → última entrega
          (a ordem respeita a sequência da lista; todos os endereços
           exceto o último viram waypoints, o último vira destination)

    Nunca define &origin= fixo — ao omiti-lo, o Google Maps usa
    automaticamente a posição atual do dispositivo como ponto de partida.

    Args:
        entregas: lista de objetos Entrega com atributos rua, numero e bairro.
        cidade:   sufixo adicionado a cada endereço (ex: "Boa Vista RR").

    Returns:
        URL completa do Google Maps, pronta para abrir no celular.

    Exemplo com 3 entregas em Boa Vista:
        https://www.google.com/maps/dir/?api=1
            &destination=Rua+C+30+Asa+Branca+Boa+Vista+RR
            &waypoints=Rua+A+10+Centro+Boa+Vista+RR|Rua+B+55+Mecejana+Boa+Vista+RR
            &travelmode=driving
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

    encoded     = [_encode(e) for e in entregas]
    destination = encoded[-1]                        # sempre o último
    waypoints   = "|".join(encoded[:-1])             # todos os anteriores

    # origin é OMITIDO — Maps usa o GPS do celular automaticamente
    BASE = "https://www.google.com/maps/dir/?api=1"
    url  = f"{BASE}&destination={destination}"
    if waypoints:
        url += f"&waypoints={waypoints}"
    url += "&travelmode=driving"

    return url
