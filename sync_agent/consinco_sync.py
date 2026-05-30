"""
Consinco → Sistema Logístico  |  Agente de Sincronização
=========================================================
Lê TB_DOCTOENTREGA do Oracle (Consinco) a cada POLL_INTERVAL segundos
e cria automaticamente clientes + entregas na API do sistema logístico.

Substitui completamente o PDV_GUI — nenhuma digitação manual necessária.
NROEMPRESA do Consinco é mapeado para filial_id via FILIAL_MAP no .env.
SEQDOCTO é rastreado separadamente por NROEMPRESA.
"""

import os
import sys
import time
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

import oracledb
import requests
from dotenv import load_dotenv

# ─── .env ─────────────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

# ─── CONFIGURAÇÕES ────────────────────────────────────────────────────────────
ORACLE_HOST     = os.getenv("ORACLE_HOST",     "")
ORACLE_PORT     = int(os.getenv("ORACLE_PORT", "1521"))
ORACLE_SERVICE  = os.getenv("ORACLE_SERVICE",  "")
ORACLE_USER     = os.getenv("ORACLE_USER",     "")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")

API_URL         = os.getenv("API_URL",        "https://sistema-de-logistica-production.up.railway.app")
API_USERNAME    = os.getenv("API_USERNAME",   "")
API_PASSWORD    = os.getenv("API_PASSWORD",   "")
POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL", "30"))
FILIAL_PADRAO   = int(os.getenv("FILIAL_PADRAO",  "2"))

# ─── MAPEAMENTO NROEMPRESA → filial_id ────────────────────────────────────────
def _parse_filial_map(raw: str) -> dict:
    mapa = {}
    for par in raw.split(","):
        par = par.strip()
        if ":" in par:
            k, v = par.split(":", 1)
            try:
                mapa[int(k.strip())] = int(v.strip())
            except ValueError:
                pass
    return mapa

FILIAL_MAP: dict = _parse_filial_map(os.getenv("FILIAL_MAP", "1:2,2:3,4:4,5:5,9:7,16:6"))

def filial_id_para(nroempresa) -> int:
    try:
        return FILIAL_MAP.get(int(nroempresa), FILIAL_PADRAO)
    except (TypeError, ValueError):
        return FILIAL_PADRAO

TRACKING_DB = Path(__file__).parent / "sync_tracking.db"

# ─── LOGGING TÉCNICO (sync_agent.log) ────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "sync_agent.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("consinco_sync")

# ─── LOG LEGÍVEL (registro_entregas.txt) ─────────────────────────────────────
_REGISTRO_PATH = Path(__file__).parent / "registro_entregas.txt"

def _escrever_registro(linha: str):
    """Adiciona uma linha ao registro_entregas.txt com timestamp."""
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    with open(_REGISTRO_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {linha}\n")


# ─── RASTREAMENTO LOCAL (SQLite) ───────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(TRACKING_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS synced (
            nroempresa  INTEGER NOT NULL,
            seqdocto    INTEGER NOT NULL,
            checkout    INTEGER,
            filial_id   INTEGER,
            synced_at   TEXT,
            PRIMARY KEY (nroempresa, seqdocto)
        )
    """)
    con.commit()
    con.close()

def is_synced(nroempresa: int, seqdocto: int) -> bool:
    con = sqlite3.connect(TRACKING_DB)
    found = con.execute(
        "SELECT 1 FROM synced WHERE nroempresa=? AND seqdocto=?",
        (nroempresa, seqdocto)
    ).fetchone()
    con.close()
    return found is not None

def mark_synced(nroempresa: int, seqdocto: int, checkout, filial_id: int):
    con = sqlite3.connect(TRACKING_DB)
    con.execute(
        "INSERT OR IGNORE INTO synced(nroempresa, seqdocto, checkout, filial_id, synced_at) VALUES(?,?,?,?,?)",
        (nroempresa, seqdocto, checkout, filial_id, datetime.now().isoformat()),
    )
    con.commit()
    con.close()

def get_synced_set() -> set:
    """Retorna um set {(nroempresa, seqdocto)} de todos os registros já vistos."""
    con = sqlite3.connect(TRACKING_DB)
    rows = con.execute("SELECT nroempresa, seqdocto FROM synced").fetchall()
    con.close()
    return {(int(r[0]), int(r[1])) for r in rows}


# ─── API DO SISTEMA LOGÍSTICO ─────────────────────────────────────────────────
class LogisticaAPI:
    def __init__(self):
        self.s = requests.Session()

    def login(self) -> bool:
        try:
            r = self.s.post(
                f"{API_URL}/login",
                data={"username": API_USERNAME, "password": API_PASSWORD},
                allow_redirects=False,
                timeout=15,
            )
            ok = r.status_code in (200, 302, 303)
            log.info("Login na API: %s", "OK" if ok else f"FALHOU (HTTP {r.status_code})")
            return ok
        except requests.RequestException as e:
            log.error("Erro de conexão com a API: %s", e)
            return False

    def get_cliente(self, documento: str):
        try:
            r = self.s.get(f"{API_URL}/clientes/{documento}", timeout=10)
            return r.json() if r.status_code == 200 else None
        except requests.RequestException:
            return None

    def criar_cliente(self, payload: dict):
        try:
            r = self.s.post(f"{API_URL}/clientes/", json=payload, timeout=10)
            if r.status_code in (200, 201):
                return r.json()
            log.error("Erro ao criar cliente: HTTP %s | %s", r.status_code, r.text[:300])
            return None
        except requests.RequestException as e:
            log.error("Erro de rede ao criar cliente: %s", e)
            return None

    def criar_entrega(self, payload: dict):
        try:
            r = self.s.post(f"{API_URL}/entregas/", json=payload, timeout=10)
            if r.status_code in (200, 201):
                return r.json()
            log.error("Erro ao criar entrega: HTTP %s | %s", r.status_code, r.text[:300])
            return None
        except requests.RequestException as e:
            log.error("Erro de rede ao criar entrega: %s", e)
            return None


# ─── QUERY ORACLE ─────────────────────────────────────────────────────────────
# Busca TODAS as linhas da tabela — a filtragem de "já visto" é feita em Python.
# Usa SEQPESSOA como identificador do cliente (documento + nome gerado).
BASE_SELECT = """
    SELECT
        d.NROEMPRESA,
        d.SEQDOCTO,
        d.NROCHECKOUT,
        NVL(d.LOGRADOURO,             'NAO INFORMADO') AS LOGRADOURO,
        NVL(TO_CHAR(d.NROLOGRADOURO), 'S/N')           AS NUMERO,
        NVL(d.BAIRRO,                 'NAO INFORMADO') AS BAIRRO,
        NVL(d.COMPLEMENTO,            '')              AS COMPLEMENTO,
        NVL(d.CIDADE,                 'NAO INFORMADA') AS CIDADE,
        NVL(d.UF,                     '')              AS UF,
        NVL(d.CEP,                    '')              AS CEP,
        NVL(d.OBSERVACAO,             '')              AS OBSERVACAO,
        NVL(TO_CHAR(d.FONE),          '')              AS FONE,
        d.SEQPESSOA
    FROM TB_DOCTOENTREGA d
    ORDER BY d.NROEMPRESA, d.SEQDOCTO ASC
"""

def buscar_entregas_novas(conn) -> list:
    """
    Busca TODAS as linhas da tabela Oracle e retorna apenas as que ainda não
    foram sincronizadas. Detecta qualquer linha nova, independente do SEQDOCTO.
    """
    try:
        cur = conn.cursor()
        cur.execute(BASE_SELECT)
        cols = [c[0] for c in cur.description]
        todos = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()

        ja_vistos = get_synced_set()
        novos = [r for r in todos
                 if (int(r["NROEMPRESA"]), int(r["SEQDOCTO"])) not in ja_vistos]

        log.info(
            "Tabela Oracle: %d linhas | Já sincronizadas: %d | Novas: %d",
            len(todos), len(todos) - len(novos), len(novos),
        )
        return novos
    except oracledb.DatabaseError as e:
        log.error("Erro ao consultar TB_DOCTOENTREGA: %s", e)
        return []


# ─── HELPER: converte qualquer valor Oracle para str limpa ────────────────────
def _s(val) -> str:
    """Converte int/float/None vindos do Oracle para str sem quebrar no .strip()."""
    if val is None:
        return ""
    return str(val).strip()


# ─── PROCESSAMENTO ────────────────────────────────────────────────────────────
def processar(api: LogisticaAPI, registros: list):
    for r in registros:
        nroempresa = int(r.get("NROEMPRESA", 1))
        seqdocto   = int(r["SEQDOCTO"])
        filial_id  = filial_id_para(nroempresa)

        if is_synced(nroempresa, seqdocto):
            continue

        # SEQPESSOA é o identificador único do cliente no Consinco
        seq_pessoa = str(r["SEQPESSOA"])
        nome       = f"CLIENTE {seq_pessoa}"
        fone       = _s(r.get("FONE")) or None

        # 1. Localizar ou criar cliente pelo SEQPESSOA (usado como documento)
        cliente = api.get_cliente(seq_pessoa)
        if not cliente:
            log.info("SeqPessoa %s não encontrado → criando cliente…", seq_pessoa)
            cliente = api.criar_cliente({
                "nome":             nome,
                "documento":        seq_pessoa,
                "telefone":         fone,
                "rua":              _s(r["LOGRADOURO"]),
                "numero":           _s(r["NUMERO"]),
                "bairro":           _s(r["BAIRRO"]),
                "ponto_referencia": _s(r.get("COMPLEMENTO")) or None,
            })

        if not cliente:
            log.error("Não foi possível garantir cliente para emp=%s seq=%s — pulando.", nroempresa, seqdocto)
            continue

        # 2. Observação: apenas o campo real do Consinco (sem misturar cidade/UF/CEP)
        obs = _s(r.get("OBSERVACAO")) or None

        # 3. Criar entrega com municipio, uf, cep e IDs do Consinco
        def _to_int(val):
            try:
                return int(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        entrega = api.criar_entrega({
            "cupom_fiscal": str(r["NROCHECKOUT"]),
            "cliente_id":   cliente["id"],
            "rua":          _s(r["LOGRADOURO"]),
            "numero":       _s(r["NUMERO"]),
            "bairro":       _s(r["BAIRRO"]),
            "municipio":    _s(r.get("CIDADE"))  or None,
            "uf":           _s(r.get("UF"))     or None,
            "cep":          _s(r.get("CEP"))    or None,
            "observacao":   obs,
            "filial_id":    filial_id,
            # IDs de rastreabilidade do Consinco
            "nro_checkout": _to_int(r.get("NROCHECKOUT")),
            "seq_docto":    _to_int(r.get("SEQDOCTO")),
            "seq_pessoa":   _to_int(r.get("SEQPESSOA")),
        })

        if entrega:
            mark_synced(nroempresa, seqdocto, r["NROCHECKOUT"], filial_id)
            log.info(
                "✓  emp %-3s  SEQDOCTO %-8s  →  filial %-3s  |  Entrega #%s  (%s)",
                nroempresa, seqdocto, filial_id, entrega.get("id"), nome,
            )
            # ── Registro legível ──────────────────────────────────────────
            _escrever_registro(
                f"OK  | Entrega #{entrega.get('id'):<6} "
                f"| Checkout {r['NROCHECKOUT']:<8} "
                f"| SeqDocto {seqdocto:<8} "
                f"| SeqPessoa {seq_pessoa:<8} "
                f"| Filial {filial_id}"
            )
            _escrever_registro(
                f"     Endereco: {_s(r['LOGRADOURO'])}, {_s(r['NUMERO'])} — {_s(r['BAIRRO'])}"
                + (f", {_s(r['CIDADE'])}/{_s(r['UF'])}" if r.get('CIDADE') else "")
            )
        else:
            log.error("✗  emp %s  SEQDOCTO %s  →  falhou criar entrega.", nroempresa, seqdocto)
            # ── Registro legível ──────────────────────────────────────────
            _escrever_registro(
                f"ERRO| Empresa {nroempresa} | SeqDocto {seqdocto} "
                f"| SeqPessoa {seq_pessoa} — falhou criar entrega na API"
            )


# ─── SEED INICIAL ─────────────────────────────────────────────────────────────
def seed_inicial_se_necessario(oracle_conn):
    """
    Na primeira vez que roda (SQLite vazio), marca TODOS os registros existentes
    na tabela Oracle como "já vistos" — sem criar entregas — para que apenas
    linhas genuinamente novas sejam importadas a partir deste momento.
    """
    con = sqlite3.connect(TRACKING_DB)
    total_local = con.execute("SELECT COUNT(*) FROM synced").fetchone()[0]
    con.close()

    if total_local > 0:
        return  # já tem dados, seed não é necessário

    log.info("Primeiro run detectado — registrando todos os registros existentes como já vistos…")
    cur = oracle_conn.cursor()
    cur.execute("SELECT NROEMPRESA, SEQDOCTO FROM TB_DOCTOENTREGA")
    existentes = [(int(r[0]), int(r[1])) for r in cur.fetchall()]
    cur.close()

    if existentes:
        agora = datetime.now().isoformat()
        con = sqlite3.connect(TRACKING_DB)
        con.executemany(
            "INSERT OR IGNORE INTO synced(nroempresa, seqdocto, synced_at) VALUES(?,?,?)",
            [(e, s, agora) for e, s in existentes],
        )
        con.commit()
        con.close()
        log.info(
            "Seed concluído: %d registros históricos ignorados. "
            "Apenas linhas novas na tabela serão importadas.",
            len(existentes),
        )
    else:
        log.info("Tabela Oracle está vazia — tudo que aparecer será importado.")


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("  Consinco Sync Agent  |  %s", datetime.now().strftime("%d/%m/%Y %H:%M"))
    log.info("  Mapeamento de filiais: %s", FILIAL_MAP)
    log.info("=" * 60)

    # Cabeçalho no registro legível
    _escrever_registro("=" * 56)
    _escrever_registro(f"  AGENTE INICIADO | Polling a cada {POLL_INTERVAL}s")
    _escrever_registro("=" * 56)

    if not API_USERNAME or not API_PASSWORD:
        log.error("API_USERNAME e API_PASSWORD não configurados no .env!")
        sys.exit(1)

    init_db()

    api = LogisticaAPI()
    # Tenta login até 10 vezes com espera crescente (DNS lento ou API temporariamente indisponível)
    for tentativa in range(1, 11):
        if api.login():
            break
        espera = min(30 * tentativa, 300)
        log.warning("Login falhou (tentativa %d/10) — aguardando %ds antes de tentar novamente…", tentativa, espera)
        time.sleep(espera)
    else:
        log.error("Login na API falhou após 10 tentativas. Verifique API_USERNAME / API_PASSWORD no .env")
        sys.exit(1)

    dsn = oracledb.makedsn(ORACLE_HOST, ORACLE_PORT, service_name=ORACLE_SERVICE)
    log.info("Oracle: %s@%s  |  polling a cada %ss", ORACLE_USER, dsn, POLL_INTERVAL)

    while True:
        try:
            with oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=dsn) as oracle_conn:
                log.info("Conexão Oracle estabelecida.")

                # Seed automático no primeiro run
                seed_inicial_se_necessario(oracle_conn)

                while True:
                    registros = buscar_entregas_novas(oracle_conn)
                    if registros:
                        log.info("%d novo(s) registro(s) encontrado(s) — processando…", len(registros))
                        processar(api, registros)

                    time.sleep(POLL_INTERVAL)

        except oracledb.DatabaseError as e:
            log.error("Erro Oracle: %s — reconectando em 60s…", e)
            time.sleep(60)
        except KeyboardInterrupt:
            log.info("Agente encerrado pelo usuário.")
            break
        except Exception as e:
            log.error("Erro inesperado: %s — reiniciando em 30s…", e)
            time.sleep(30)


if __name__ == "__main__":
    main()
