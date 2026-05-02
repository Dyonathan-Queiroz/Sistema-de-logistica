import requests

BASE_URL = "http://127.0.0.1:8000"

def testar_fluxo_pdv():
    print("--- Iniciando teste do PDV (Fluxo Corrigido) ---")
    
    # 1. Definindo dados do Cliente (incluindo o ponto de referência aqui)
    cpf_teste = "123456789001"
    cliente_payload = {
        "nome": "Cliente Teste 1",
        "documento": cpf_teste,
        "telefone": "99999-0001",
        "rua": "Rua das Flores",
        "numero": "123",
        "bairro": "Centro",
        "ponto_referencia": "Em frente à praça principal" 
    }
    
    # Tenta buscar, se não achar, cria o cliente
    response = requests.get(f"{BASE_URL}/clientes/{cpf_teste}")
    if response.status_code == 404:
        print("Cadastrando novo cliente...")
        res_cliente = requests.post(f"{BASE_URL}/clientes/", json=cliente_payload)
        cliente = res_cliente.json()
    else:
        cliente = response.json()
        print(f"Cliente encontrado: {cliente['nome']}")

    cliente_id = cliente['id']
    
    # 2. Lançar a entrega (AGORA SEM O PONTO DE REFERÊNCIA)
    # A entrega puxa as informações de localização a partir do cliente
    print(f"Lançando entrega para o ID {cliente_id}...")
    entrega_payload = {
        "cupom_fiscal": "CF-100200",
        "cliente_id": cliente_id,
        "rua": cliente['rua'],
        "numero": cliente['numero'],
        "bairro": cliente['bairro'],
        "observacao": "Entregar à tarde, após as 14h."
    }
    
    res_entrega = requests.post(f"{BASE_URL}/entregas/", json=entrega_payload)
    
    if res_entrega.status_code == 200:
        print("✅ Sucesso! Entrega lançada com sucesso.")
        print(f"Dados salvos: {res_entrega.json()}")
    else:
        print(f"❌ Erro ao registrar entrega: {res_entrega.status_code} - {res_entrega.text}")

if __name__ == "__main__":
    testar_fluxo_pdv()