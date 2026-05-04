"""
Cliente HTTP do PDV para o backend FastAPI.

Um único requests.Session() é mantido durante toda a execução do aplicativo,
preservando os cookies de autenticação (user_role, user_id, user_filial_id)
após o login.
"""

import os
import requests

BASE_URL = os.getenv("API_BASE_URL", "https://sistema-de-logistica-production.up.railway.app")

_session = requests.Session()
_user_info: dict = {}  # populado em login()


def login(username: str, password: str) -> bool:
    """
    Autentica contra o backend.
    Envia form-data (igual ao formulário HTML) e captura os cookies da resposta.
    Retorna True se o login foi bem-sucedido (303 redirect), False caso contrário.
    """
    try:
        resp = _session.post(
            f"{BASE_URL}/login",
            data={"username": username, "password": password},
            allow_redirects=False,  # captura o 303 sem seguir o redirect
            timeout=5,
        )
        if resp.status_code == 303:
            _user_info["id"] = _int_or_none(_session.cookies.get("user_id"))
            _user_info["role"] = _session.cookies.get("user_role")
            _user_info["filial_id"] = _int_or_none(_session.cookies.get("user_filial_id"))
            return True
        return False
    except requests.exceptions.ConnectionError:
        return False


def buscar_cliente(documento: str) -> dict | None:
    """Busca cliente por CPF/CNPJ. Retorna dict ou None se não encontrado."""
    try:
        resp = _session.get(f"{BASE_URL}/clientes/{documento}", timeout=5)
        return resp.json() if resp.status_code == 200 else None
    except requests.exceptions.RequestException:
        return None


def cadastrar_cliente(dados: dict) -> bool:
    """Cadastra novo cliente. Retorna True em caso de sucesso."""
    payload = dict(dados)

    # Campos de texto → MAIÚSCULAS (consistência no banco)
    for campo in ("nome", "rua", "numero", "bairro", "municipio"):
        if payload.get(campo):
            payload[campo] = payload[campo].strip().upper()

    # Estado: maiúscula + máximo 2 chars (evita 'Data too long' no String(2))
    if payload.get("estado"):
        payload["estado"] = payload["estado"].strip().upper()[:2]

    try:
        resp = _session.post(f"{BASE_URL}/clientes/", json=payload, timeout=5)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def lancar_entrega(dados: dict) -> tuple[bool, str]:
    """
    Lança uma entrega no backend.
    Injeta filial_id e operador_id vindos da sessão autenticada.
    Retorna (sucesso, mensagem).
    """
    payload = {**dados}
    payload.setdefault("filial_id", _user_info.get("filial_id") or 1)
    payload.setdefault("operador_id", _user_info.get("id"))

    try:
        resp = _session.post(f"{BASE_URL}/entregas/", json=payload, timeout=5)
        return resp.status_code == 200, resp.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def get_user_info() -> dict:
    """Retorna informações do usuário autenticado na sessão atual."""
    return dict(_user_info)


# --- helpers ---

def _int_or_none(value) -> int | None:
    try:
        return int(value) if value else None
    except (ValueError, TypeError):
        return None
