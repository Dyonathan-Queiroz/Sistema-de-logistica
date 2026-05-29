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

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "sync_agent.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("consinco_sync")


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

def ultimo_seq_por_empresa() -> dict:
    """Retorna {nroempresa: max_seqdocto} para todas as empresas já sincronizadas."""
    con = sqlite3.connect(TRACKING_DB)
    rows = con.execute(
        "SELECT nroempresa, MAX(seqdocto) FROM synced GROUP BY nroempresa"
    ).fetchall()
    con.close()
    return {int(r[0]): int(r[1]) for r in rows if r[1] is not None}

def seed_empresa(nroempresa: int, seqdocto: int):
    """Define o ponto de partida para uma empresa sem importar histórico."""
    con = sqlite3.connect(TRACKING_DB)
    con.execute(
        "INSERT OR IGNORE INTO synced(nroempresa, seqdocto, checkout, filial_id, synced_at) VALUES(?,?,NULL,NULL,?)",
        (nroempresa, seqdocto, datetime.now().isoformat()),
    )
    con.commit()
    con.close()
    log.info("Seed: empresa %s iniciará a partir do SEQDOCTO %s", nroempresa, seqdocto)


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
def _build_where(seqs_por_empresa: dict) -> tuple:
    """
    Monta cláusula WHERE dinâmica por empresa.
    Retorna (where_sql, bind_params).

    Ex: seqs_por_empresa = {1: 57500, 2: 105800}
    → WHERE (d.NROEMPRESA=:e1 AND d.SEQDOCTO>:s1) OR (d.NROEMPRESA=:e2 AND d.SEQDOCTO>:s2)
    """
    if not seqs_por_empresa:
        return "1=1", {}   # sem filtro: busca tudo (primeiro run após seed)

    partes = []
    params = {}
    for i, (emp, seq) in enumerate(seqs_por_empresa.items()):
        partes.append(f"(d.NROEMPRESA=:e{i} AND d.SEQDOCTO>:s{i})")
        params[f"e{i}"] = emp
        params[f"s{i}"] = seq

    # Empresas ainda não vistas: incluir
    empresas_conhecidas = list(seqs_por_empresa.keys())
    if empresas_conhecidas:
        placeholders = ",".join([f":k{i}" for i in range(len(empresas_conhecidas))])
        partes.append(f"d.NROEMPRESA NOT IN ({placeholders})")
        for i, emp in enumerate(empresas_conhecidas):
            params[f"k{i}"] = emp

    return " OR ".join(partes), params


BASE_SELECT = """
    SELECT
        d.NROEMPRESA,
        d.SEQDOCTO,
        d.NROCHECKOUT,
        NVL(d.LOGRADOURO,             'NAO INFORMADO')               AS LOGRADOURO,
        NVL(TO_CHAR(d.NROLOGRADOURO), 'S/N')                        AS NUMERO,
        NVL(d.BAIRRO,                 'NAO INFORMADO')               AS BAIRRO,
        NVL(d.COMPLEMENTO,            '')                            AS COMPLEMENTO,
        NVL(d.CIDADE,                 'NAO INFORMADA')               AS CIDADE,
        NVL(d.UF,                     '')                            AS UF,
        NVL(d.CEP,                    '')                            AS CEP,
        NVL(d.OBSERVACAO,             '')                            AS OBSERVACAO,
        NVL(TO_CHAR(d.FONE),          '')                            AS FONE,
        d.SEQPESSOA,
        {nome_col}                                                   AS NOME,
        {doc_col}                                                     AS DOCUMENTO
    FROM TB_DOCTOENTREGA d
    {join}
    WHERE {where}
    ORDER BY d.NROEMPRESA, d.SEQDOCTO ASC
"""

def buscar_entregas(conn, seqs_por_empresa: dict) -> list:
    where, params = _build_where(seqs_por_empresa)

    queries = [
        # com JOIN em TB_PESSOACLIENTE
        BASE_SELECT.format(
            nome_col="NVL(p.NOMEPESSOA, 'CLIENTE ' || TO_CHAR(d.SEQPESSOA))",
            doc_col="NVL(p.NROCPFCNPJ, TO_CHAR(d.SEQPESSOA))",
            join="LEFT JOIN TB_PESSOACLIENTE p ON p.SEQPESSOA = d.SEQPESSOA",
            where=where,
        ),
        # fallback sem JOIN
        BASE_SELECT.format(
            nome_col="'CLIENTE ' || TO_CHAR(d.SEQPESSOA)",
            doc_col="TO_CHAR(d.SEQPESSOA)",
            join="",
            where=where,
        ),
    ]

    for query, label in zip(queries, ["completa", "simples"]):
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            return rows
        except oracledb.DatabaseError as e:
            log.warning("Query %s falhou (%s) — tentando modo simples…", label, e)

    log.error("Ambas as queries falharam.")
    return []


# ─── PROCESSAMENTO ────────────────────────────────────────────────────────────
def processar(api: LogisticaAPI, registros: list):
    for r in registros:
        nroempresa = int(r.get("NROEMPRESA", 1))
        seqdocto   = int(r["SEQDOCTO"])
        filial_id  = filial_id_para(nroempresa)

        if is_synced(nroempresa, seqdocto):
            continue

        nome      = str(r.get("NOME")      or f"CLIENTE {r['SEQPESSOA']}")
        documento = str(r.get("DOCUMENTO") or r["SEQPESSOA"])
        fone      = str(r.get("FONE")      or "").strip() or "00000000000"

        # 1. Localizar ou criar cliente
        cliente = api.get_cliente(documento)
        if not cliente:
            log.info("Cliente '%s' não encontrado → criando…", nome)
            cliente = api.criar_cliente({
                "nome":             nome,
                "documento":        documento,
                "telefone":         fone,
                "rua":              r["LOGRADOURO"],
                "numero":           r["NUMERO"],
                "bairro":           r["BAIRRO"],
                "ponto_referencia": r["COMPLEMENTO"] or None,
            })

        if not cliente:
            log.error("Não foi possível garantir cliente para emp=%s seq=%s — pulando.", nroempresa, seqdocto)
            continue

        # 2. Observação: apenas o campo real do Consinco (sem misturar cidade/UF/CEP)
        obs = (r.get("OBSERVACAO") or "").strip() or None

        # 3. Criar entrega com municipio, uf e cep em colunas próprias
        entrega = api.criar_entrega({
            "cupom_fiscal": str(r["NROCHECKOUT"]),
            "cliente_id":   cliente["id"],
            "rua":          r["LOGRADOURO"],
            "numero":       r["NUMERO"],
            "bairro":       r["BAIRRO"],
            "municipio":    (r.get("CIDADE")    or "").strip() or None,
            "uf":           (r.get("UF")        or "").strip() or None,
            "cep":          (r.get("CEP")       or "").strip() or None,
            "observacao":   obs,
            "filial_id":    filial_id,
        })

        if entrega:
            mark_synced(nroempresa, seqdocto, r["NROCHECKOUT"], filial_id)
            log.info(
                "✓  emp %-3s  SEQDOCTO %-8s  →  filial %-3s  |  Entrega #%s  (%s)",
                nroempresa, seqdocto, filial_id, entrega.get("id"), nome,
            )
        else:
            log.error("✗  emp %s  SEQDOCTO %s  →  falhou criar entrega.", nroempresa, seqdocto)


# ─── SEED INICIAL ─────────────────────────────────────────────────────────────
def seed_inicial_se_necessario(oracle_conn):
    """
    Na primeira vez que roda, consulta o MAX(SEQDOCTO) por empresa
    e salva como ponto de partida — evita importar histórico antigo.
    """
    seqs = ultimo_seq_por_empresa()
    if seqs:
        return  # já tem dados, não precisa seed

    log.info("Primeiro run detectado — aplicando seed inicial por empresa…")
    cur = oracle_conn.cursor()
    cur.execute("SELECT NROEMPRESA, MAX(SEQDOCTO) FROM TB_DOCTOENTREGA GROUP BY NROEMPRESA")
    for nroempresa, max_seq in cur.fetchall():
        if max_seq:
            seed_empresa(int(nroempresa), int(max_seq))
    cur.close()
    log.info("Seed concluído. O agente vai capturar apenas registros novos daqui em diante.")


# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("  Consinco Sync Agent  |  %s", datetime.now().strftime("%d/%m/%Y %H:%M"))
    log.info("  Mapeamento de filiais: %s", FILIAL_MAP)
    log.info("=" * 60)

    if not API_USERNAME or not API_PASSWORD:
        log.error("API_USERNAME e API_PASSWORD não configurados no .env!")
        sys.exit(1)

    init_db()

    api = LogisticaAPI()
    if not api.login():
        log.error("Login na API falhou. Verifique API_USERNAME / API_PASSWORD no .env")
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
                    seqs = ultimo_seq_por_empresa()
                    log.info("Verificando novos registros  |  seqs por empresa: %s", seqs)

                    registros = buscar_entregas(oracle_conn, seqs)
                    if registros:
                        log.info("%d novo(s) registro(s) encontrado(s).", len(registros))
                        processar(api, registros)
                    else:
                        log.info("Nenhum registro novo.")

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
