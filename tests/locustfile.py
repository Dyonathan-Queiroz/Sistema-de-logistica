"""
Teste de carga — Sistema Logístico Gavião
==========================================
Simula dois perfis de usuário em uso simultâneo:
  GestorUser    — dashboard, log, frota, desempenho, clientes
  EntregadorUser — dashboard entregador, turno, checklist

Instalação:
    pip install locust

Uso básico (interface web):
    locust -f tests/locustfile.py --host https://SEU-DOMINIO.up.railway.app

Uso headless:
    locust -f tests/locustfile.py --host https://SEU-DOMINIO.up.railway.app \
           --headless -u 5 -r 1 -t 2m --html tests/relatorio.html

IMPORTANTE: O sistema tem rate limiter de 5 logins/min por IP.
Use no máximo 5 usuários por vez neste teste.
"""

import os
import random
from locust import HttpUser, task, between, events

# ── Credenciais ────────────────────────────────────────────────────────────
GESTOR_USER     = os.getenv("GESTOR_USER",     "admin")
GESTOR_PASS     = os.getenv("GESTOR_PASS",     "admin123")
ENTREGADOR_USER = os.getenv("ENTREGADOR_USER", "entregador")
ENTREGADOR_PASS = os.getenv("ENTREGADOR_PASS", "entregador123")


# ═══════════════════════════════════════════════════════════════════════════
# PERFIL: GESTOR
# ═══════════════════════════════════════════════════════════════════════════
class GestorUser(HttpUser):
    weight = 60
    wait_time = between(2, 5)

    def on_start(self):
        with self.client.post(
            "/login",
            data={"username": GESTOR_USER, "password": GESTOR_PASS},
            allow_redirects=False,
            catch_response=True,
            name="[setup] login gestor",
        ) as resp:
            if resp.status_code in (301, 302, 303):
                resp.success()
            elif resp.status_code == 429:
                resp.failure("Rate limit atingido — reduza -u ou aguarde 60s")
                self.stop()
            else:
                resp.failure(f"Login falhou: HTTP {resp.status_code}")
                self.stop()

    @task(10)
    def dashboard_gestor(self):
        self.client.get("/gestor", name="/gestor (dashboard)")

    @task(8)
    def log_entregas(self):
        self.client.get("/gestor/log", name="/gestor/log")

    @task(5)
    def ao_vivo(self):
        self.client.get("/gestor/ao-vivo", name="/gestor/ao-vivo")

    @task(4)
    def frota_dashboard(self):
        self.client.get("/frota/dashboard", name="/frota/dashboard")

    @task(3)
    def frota_manutencao(self):
        self.client.get("/frota/manutencao", name="/frota/manutencao")

    @task(3)
    def frota_alertas(self):
        self.client.get("/frota/alertas", name="/frota/alertas")

    @task(2)
    def frota_historico_geral(self):
        self.client.get("/frota/historico-geral", name="/frota/historico-geral")

    @task(2)
    def frota_ranking(self):
        self.client.get("/frota/ranking", name="/frota/ranking")

    @task(2)
    def desempenho(self):
        self.client.get("/gestor/desempenho", name="/gestor/desempenho")

    @task(1)
    def buscar_cliente(self):
        termo = random.choice(["Maria", "João", "Jose", "Ana", "Paulo"])
        self.client.get(
            f"/gestor/clientes/buscar?q={termo}",
            name="/gestor/clientes/buscar",
        )

    @task(1)
    def nova_entrega(self):
        self.client.get("/gestor/entrega/nova", name="/gestor/entrega/nova")


# ═══════════════════════════════════════════════════════════════════════════
# PERFIL: ENTREGADOR
# ═══════════════════════════════════════════════════════════════════════════
class EntregadorUser(HttpUser):
    weight = 40
    wait_time = between(5, 12)

    def on_start(self):
        with self.client.post(
            "/login",
            data={"username": ENTREGADOR_USER, "password": ENTREGADOR_PASS},
            allow_redirects=False,
            catch_response=True,
            name="[setup] login entregador",
        ) as resp:
            if resp.status_code in (301, 302, 303):
                resp.success()
            elif resp.status_code == 429:
                resp.failure("Rate limit atingido — reduza -u ou aguarde 60s")
                self.stop()
            else:
                resp.failure(f"Login falhou: HTTP {resp.status_code}")
                self.stop()

    @task(10)
    def dashboard_entregador(self):
        self.client.get("/entregador", name="/entregador (dashboard)")

    @task(4)
    def frota_turno(self):
        self.client.get("/frota/turno", name="/frota/turno")

    @task(2)
    def frota_checklist(self):
        self.client.get("/frota/checklist", name="/frota/checklist")

    @task(1)
    def frota_ranking(self):
        self.client.get("/frota/ranking", name="/frota/ranking")


# ── Banner inicial ─────────────────────────────────────────────────────────
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("\n" + "═" * 60)
    print("  TESTE DE CARGA — SISTEMA LOGÍSTICO GAVIÃO")
    print("═" * 60)
    print(f"  Host:       {environment.host}")
    print(f"  Gestor:     {GESTOR_USER}")
    print(f"  Entregador: {ENTREGADOR_USER}")
    print("  Limite: máx 5 usuários (rate limiter)")
    print("═" * 60 + "\n")
