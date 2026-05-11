"""
app/utils.py — Funções utilitárias compartilhadas pelo backend.
"""
from urllib.parse import quote_plus


def gerar_link_rota(entregas, cidade: str = "") -> str:
    """
    Gera um link de rota otimizada no Google Maps para uma lista de entregas.

    Regras:
        - 0 entregas → retorna ""
        - 1 entrega  → link simples (só destination, sem origin fixo)
        - 2+ entregas → origin = primeira entrega,
                        destination = última entrega,
                        waypoints = todas as do meio (separadas por "|")

    Args:
        entregas: lista de objetos Entrega com atributos rua, numero e bairro.
        cidade:   sufixo adicionado a cada endereço (ex: "Boa Vista RR").
                  Deixe vazio para não incluir cidade — o Maps usará a
                  localização atual do dispositivo como referência.

    Returns:
        URL completa do Google Maps, pronta para abrir no celular.

    Exemplo de saída com 3 entregas em Boa Vista:
        https://www.google.com/maps/dir/?api=1
            &origin=Rua+A+100+Centro+Boa+Vista+RR
            &destination=Rua+C+30+Asa+Branca+Boa+Vista+RR
            &waypoints=Rua+B+55+Mecejana+Boa+Vista+RR
            &travelmode=driving
    """
    if not entregas:
        return ""

    def _encode(e) -> str:
        """Monta o endereço e codifica para URL (espaços → '+')."""
        partes = [
            str(e.rua or "").strip(),
            str(e.numero or "").strip(),
            str(e.bairro or "").strip(),
        ]
        if cidade:
            partes.append(cidade.strip())
        endereco = " ".join(p for p in partes if p)
        return quote_plus(endereco)

    encoded = [_encode(e) for e in entregas]

    BASE = "https://www.google.com/maps/dir/?api=1"

    if len(encoded) == 1:
        # Entrega única: abre destino sem origin fixo (Maps usa GPS do entregador)
        return f"{BASE}&destination={encoded[0]}&travelmode=driving"

    origin      = encoded[0]
    destination = encoded[-1]
    # Waypoints intermediários separados por "|" (literal, não codificado)
    waypoints   = "|".join(encoded[1:-1])

    url = f"{BASE}&origin={origin}&destination={destination}"
    if waypoints:
        url += f"&waypoints={waypoints}"
    url += "&travelmode=driving"

    return url
