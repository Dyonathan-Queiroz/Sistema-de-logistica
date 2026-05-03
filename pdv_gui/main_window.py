import sys
import threading
import win32print
import win32event
import win32api
import winerror
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QMessageBox,
    QDialog, QFormLayout, QTextEdit, QComboBox,
    QSystemTrayIcon, QMenu,
)
from PyQt6.QtGui import (
    QShortcut, QKeySequence, QAction,
    QIcon, QPixmap, QPainter, QColor, QBrush,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal

from pdv_gui.api_client import buscar_cliente, lancar_entrega, cadastrar_cliente, login as api_login

# ---------------------------------------------------------------------------
# Sinal seguro para comunicação pynput → Qt (threads diferentes)
# ---------------------------------------------------------------------------

class _HotkeyEmitter(QObject):
    mostrar = pyqtSignal()

_emitter = _HotkeyEmitter()


def _iniciar_listener_f10() -> None:
    """Escuta F10 globalmente em thread daemon; emite sinal thread-safe para Qt.

    Usa on_release para rastrear o estado da tecla e evitar disparos duplos
    causados pela distinção WM_SYSKEYDOWN / WM_KEYDOWN do Windows para F10.
    """
    def _run():
        from pynput import keyboard as kb
        _pressionado = False

        def on_press(key):
            nonlocal _pressionado
            if key == kb.Key.f10 and not _pressionado:
                _pressionado = True
                _emitter.mostrar.emit()

        def on_release(key):
            nonlocal _pressionado
            if key == kb.Key.f10:
                _pressionado = False

        with kb.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Ícone do system tray (círculo vermelho gerado em memória)
# ---------------------------------------------------------------------------

def _criar_icone() -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor("#d32f2f")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 28, 28)
    p.end()
    return QIcon(pix)


# ---------------------------------------------------------------------------
# Estilo
# ---------------------------------------------------------------------------

ESTILO = """
    QWidget      { font-size: 16px; font-family: 'Arial'; }
    QLineEdit    { padding: 10px; border: 2px solid #555;
                   border-radius: 5px; font-size: 16px; }
    QLineEdit:focus { border-color: #d32f2f; }
    QPushButton  { background-color: #d32f2f; color: white; font-weight: bold;
                   padding: 12px; border-radius: 8px; }
    QPushButton:hover    { background-color: #b71c1c; }
    QPushButton:focus    { border: 2px solid #fff; outline: none; }
    QPushButton:disabled { background-color: #888; }
    QLabel       { font-size: 16px; color: #333; }
    QLabel#titulo { font-size: 22px; font-weight: bold; }
    QLabel#dicas  { font-size: 12px; color: #888; }
    QComboBox    { padding: 6px; border: 2px solid #555; border-radius: 5px; }
    QComboBox:focus { border-color: #d32f2f; }
"""

# ---------------------------------------------------------------------------
# Impressão via driver Windows (win32print) — sem alteração
# ---------------------------------------------------------------------------

ESC = b'\x1b'
GS  = b'\x1d'

def _enc(texto: str) -> bytes:
    return texto.encode('cp850', errors='replace')

def listar_impressoras() -> list[str]:
    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return [p[2] for p in win32print.EnumPrinters(flags, None, 1)]
    except Exception:
        return []

def impressora_padrao() -> str:
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return ""

def imprimir_cupom_entrega(cliente: str, telefone: str, rua: str, numero: str,
                           bairro: str, municipio: str, estado: str,
                           pedido_id: str, obs: str,
                           nome_impressora: str = "") -> None:
    if not nome_impressora:
        nome_impressora = impressora_padrao()
    if not nome_impressora:
        print("Nenhuma impressora disponível.")
        return

    cupom = (
        ESC + b'@'
        # Cabeçalho centralizado
        + ESC + b'a\x01' + ESC + b'!\x30'
        + _enc("SYSTEM ENTREGAS GAVIAO\n")
        + ESC + b'!\x00'
        + _enc("====================\n")
        + ESC + b'E\x01' + _enc(f"CUPOM: #{pedido_id}\n") + ESC + b'E\x00'
        + _enc("====================\n\n")
        # Destinatário
        + ESC + b'a\x00'
        + _enc("ENTREGAR PARA:\n")
        + ESC + b'E\x01' + _enc(f"{cliente.upper()}\n") + ESC + b'E\x00'
        + (_enc(f"Tel:    {telefone}\n") if telefone else b'')
        + _enc("--------------------\n")
        # Endereço linha a linha
        + _enc(f"Rua:    {rua}\n")
        + _enc(f"Num:    {numero}\n")
        + _enc(f"Bairro: {bairro}\n")
        + (_enc(f"Cidade: {municipio}{' - ' + estado if estado else ''}\n") if municipio else b'')
        + _enc("--------------------\n")
        # Observação
        + _enc(f"OBS: {obs or '-'}\n")
        + _enc("--------------------\n\n\n")
        + GS + b'V\x41\x03'
    )
    try:
        h = win32print.OpenPrinter(nome_impressora)
        try:
            win32print.StartDocPrinter(h, 1, ("Cupom Entrega", None, "RAW"))
            try:
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, cupom)
                win32print.EndPagePrinter(h)
            finally:
                win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
    except Exception as e:
        print(f"Erro na impressão: {e}")

# ---------------------------------------------------------------------------
# Dialog: Login  (teclado: Tab entre campos, Enter para confirmar)
# ---------------------------------------------------------------------------

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDV — Login")
        self.setStyleSheet(ESTILO)
        self.setFixedSize(380, 260)
        self.login_ok = False

        layout = QVBoxLayout()
        titulo = QLabel("SISTEMA DE ENTREGAS")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(titulo)

        form = QFormLayout()
        self.input_user = QLineEdit()
        self.input_user.setPlaceholderText("Usuário")
        self.input_senha = QLineEdit()
        self.input_senha.setPlaceholderText("Senha")
        self.input_senha.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Usuário:", self.input_user)
        form.addRow("Senha:", self.input_senha)
        layout.addLayout(form)

        self.lbl_erro = QLabel("")
        self.lbl_erro.setStyleSheet("color: red; font-size: 13px;")
        self.lbl_erro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_erro)

        self.btn_entrar = QPushButton("ENTRAR  [Enter]")
        self.btn_entrar.clicked.connect(self._tentar_login)
        layout.addWidget(self.btn_entrar)

        self.setLayout(layout)

        # Enter em qualquer campo dispara login
        self.input_user.returnPressed.connect(self._tentar_login)
        self.input_senha.returnPressed.connect(self._tentar_login)

    def _tentar_login(self):
        username = self.input_user.text().strip()
        password = self.input_senha.text()
        if not username or not password:
            self.lbl_erro.setText("Preencha usuário e senha.")
            return
        self.btn_entrar.setEnabled(False)
        self.btn_entrar.setText("Conectando...")
        ok = api_login(username, password)
        self.btn_entrar.setEnabled(True)
        self.btn_entrar.setText("ENTRAR  [Enter]")
        if ok:
            self.login_ok = True
            self.accept()
        else:
            self.lbl_erro.setText("Usuário ou senha inválidos.")
            self.input_senha.clear()
            self.input_senha.setFocus()

# ---------------------------------------------------------------------------
# Dialog: Cadastro de cliente  (Tab percorre campos, Enter no último salva)
# ---------------------------------------------------------------------------

class CadastroClienteDialog(QDialog):
    CAMPOS = ["nome", "documento", "telefone", "rua", "numero", "bairro", "municipio", "estado"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cadastrar Novo Cliente  [ESC = cancelar]")
        self.setStyleSheet(ESTILO)
        layout = QFormLayout()
        self.campos: dict[str, QLineEdit] = {}
        for campo in self.CAMPOS:
            field = QLineEdit()
            layout.addRow(f"{campo.capitalize()}:", field)
            self.campos[campo] = field

        btn = QPushButton("Salvar Cliente  [Enter]")
        btn.clicked.connect(self._salvar)
        layout.addRow(btn)
        self.setLayout(layout)

        # Enter no último campo ou no botão confirma
        list(self.campos.values())[-1].returnPressed.connect(self._salvar)

    def showEvent(self, event):
        super().showEvent(event)
        list(self.campos.values())[0].setFocus()

    def _salvar(self):
        dados = {k: v.text() for k, v in self.campos.items()}
        if cadastrar_cliente(dados):
            QMessageBox.information(self, "Sucesso", "Cliente cadastrado!")
            self.accept()
        else:
            QMessageBox.warning(self, "Erro", "Documento já cadastrado ou falha de conexão.")

# ---------------------------------------------------------------------------
# Dialog: Lançar entrega
#
# Fluxo de teclado:
#   Cupom [Enter] → confirma direto (caminho rápido, sem obs)
#   Cupom [Tab]   → campo Obs → [Tab] → botão Confirmar → [Enter]
#   [ESC]         → cancela
# ---------------------------------------------------------------------------

class LancarEntregaDialog(QDialog):
    def __init__(self, cliente: dict, nome_impressora: str = "", parent=None):
        super().__init__(parent)
        self.cliente = cliente
        self.nome_impressora = nome_impressora
        self.setWindowTitle("Lançar Entrega  [ESC = cancelar]")
        self.setStyleSheet(ESTILO)

        layout = QFormLayout()
        cidade_linha = ""
        if cliente.get("municipio"):
            cidade_linha = f"\n{cliente['municipio']}"
            if cliente.get("estado"):
                cidade_linha += f" — {cliente['estado']}"
        info = QLabel(
            f"Cliente: {cliente['nome']}\n"
            f"{cliente['rua']}, {cliente['numero']} — {cliente['bairro']}"
            f"{cidade_linha}"
        )
        info.setStyleSheet("font-size: 14px; color: #555; margin-bottom: 8px;")
        layout.addRow(info)

        self.input_cupom = QLineEdit()
        self.input_cupom.setPlaceholderText("Número do cupom  [Enter = confirmar]")

        self.input_obs = QTextEdit()
        self.input_obs.setPlaceholderText("Observações — opcional  (Tab para avançar)")
        self.input_obs.setMaximumHeight(70)

        self.btn_confirmar = QPushButton("Confirmar e Imprimir  [F2]")
        self.btn_confirmar.clicked.connect(self._confirmar)

        dica = QLabel("F2 = Confirmar  ·  ESC = Cancelar  ·  Tab = Próximo campo")
        dica.setObjectName("dicas")
        dica.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addRow("Cupom Fiscal:", self.input_cupom)
        layout.addRow("Observações:", self.input_obs)
        layout.addRow(self.btn_confirmar)
        layout.addRow(dica)
        self.setLayout(layout)

        # F2 confirma de qualquer campo do diálogo
        QShortcut(QKeySequence("F2"), self).activated.connect(self._confirmar)

        # Enter no campo cupom também confirma (caminho rápido)
        self.input_cupom.returnPressed.connect(self._confirmar)

        # Tab order explícito: cupom → obs → botão
        self.setTabOrder(self.input_cupom, self.input_obs)
        self.setTabOrder(self.input_obs, self.btn_confirmar)

    def showEvent(self, event):
        super().showEvent(event)
        self.input_cupom.setFocus()
        self.input_cupom.clear()

    def _confirmar(self):
        cupom = self.input_cupom.text().strip()
        if not cupom:
            QMessageBox.warning(self, "Atenção", "Informe o cupom fiscal.")
            return

        dados = {
            "cupom_fiscal": cupom,
            "cliente_id": self.cliente["id"],
            "rua": self.cliente["rua"],
            "numero": self.cliente["numero"],
            "bairro": self.cliente["bairro"],
            "observacao": self.input_obs.toPlainText(),
        }
        sucesso, msg = lancar_entrega(dados)
        if sucesso:
            threading.Thread(
                target=imprimir_cupom_entrega,
                args=(
                    self.cliente["nome"],
                    self.cliente.get("telefone", ""),
                    self.cliente.get("rua", ""),
                    self.cliente.get("numero", ""),
                    self.cliente.get("bairro", ""),
                    self.cliente.get("municipio", ""),
                    self.cliente.get("estado", ""),
                    cupom,
                    self.input_obs.toPlainText(),
                    self.nome_impressora,
                ),
                daemon=True,
            ).start()
            QMessageBox.information(self, "Sucesso", "Entrega lançada! Cupom na impressão.")
            self.accept()   # sinaliza PDVApp para esconder a janela
        else:
            QMessageBox.critical(self, "Erro", f"Falha:\n{msg}")

# ---------------------------------------------------------------------------
# Janela principal do PDV
# ---------------------------------------------------------------------------

class PDVApp(QWidget):
    def __init__(self):
        super().__init__()
        self.cliente_atual: dict | None = None
        self.setWindowTitle("PDV — Entregas")
        self.setStyleSheet(ESTILO)
        self.setFixedSize(640, 380)
        # Sem barra de tarefas — aparece apenas quando chamada pelo F10
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint
        )

        layout = QVBoxLayout()
        layout.setSpacing(10)

        titulo = QLabel("PDV — LANÇAMENTO DE ENTREGAS")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(titulo)

        self.input_cpf = QLineEdit()
        self.input_cpf.setPlaceholderText("CPF / CNPJ  [Enter = buscar]")
        layout.addWidget(self.input_cpf)

        btn_row = QHBoxLayout()
        self.btn_buscar   = QPushButton("Buscar  [Enter]")
        self.btn_cadastrar = QPushButton("Novo Cliente  [F5]")
        btn_row.addWidget(self.btn_buscar)
        btn_row.addWidget(self.btn_cadastrar)
        layout.addLayout(btn_row)

        self.lbl_info = QLabel("Aguardando busca...")
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        self.btn_entrega = QPushButton("Lançar Entrega  [Enter]")
        self.btn_entrega.hide()
        layout.addWidget(self.btn_entrega)

        # Seletor de impressora
        imp_row = QHBoxLayout()
        imp_row.addWidget(QLabel("Impressora:"))
        self.combo_impressora = QComboBox()
        self._carregar_impressoras()
        imp_row.addWidget(self.combo_impressora, stretch=1)
        layout.addLayout(imp_row)

        # Dicas de teclado
        dicas = QLabel("F10 Abrir  ·  ESC Fechar  ·  Enter Buscar  ·  F1 Lançar Entrega  ·  F2 Confirmar  ·  F5 Novo Cliente")
        dicas.setObjectName("dicas")
        dicas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dicas)

        self.setLayout(layout)

        # Tab order: CPF → Buscar → Cadastrar → (Lançar) → Impressora
        self.setTabOrder(self.input_cpf,     self.btn_buscar)
        self.setTabOrder(self.btn_buscar,    self.btn_cadastrar)
        self.setTabOrder(self.btn_cadastrar, self.btn_entrega)
        self.setTabOrder(self.btn_entrega,   self.combo_impressora)

        # Conexões
        self.input_cpf.returnPressed.connect(self._buscar)
        self.btn_buscar.clicked.connect(self._buscar)
        self.btn_cadastrar.clicked.connect(self._novo_cliente)
        self.btn_entrega.clicked.connect(self._lancar_entrega)

        # Atalhos de teclado
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._esconder)
        QShortcut(QKeySequence("F5"),     self).activated.connect(self._novo_cliente)
        QShortcut(QKeySequence("F1"),     self).activated.connect(self._lancar_entrega)

        # System tray
        self._tray = self._criar_tray()

    # --- Tray icon ---

    def _criar_tray(self) -> QSystemTrayIcon:
        icone = _criar_icone()
        tray = QSystemTrayIcon(icone, self)
        tray.setToolTip("PDV Entregas — F10 para abrir")

        menu = QMenu()
        acao_mostrar = QAction("Abrir PDV  [F10]", self)
        acao_mostrar.triggered.connect(self._mostrar)
        acao_sair = QAction("Sair", self)
        acao_sair.triggered.connect(QApplication.instance().quit)
        menu.addAction(acao_mostrar)
        menu.addSeparator()
        menu.addAction(acao_sair)

        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._mostrar()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        tray.show()
        return tray

    # --- Mostrar / Esconder ---

    def _mostrar(self) -> None:
        """Traz a janela para frente e foca no campo CPF."""
        if self.isVisible():
            self.raise_()
            self.activateWindow()
            return
        self._resetar()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_cpf.setFocus()

    def _esconder(self) -> None:
        """Esconde a janela; programa continua rodando em segundo plano."""
        self.hide()

    def _resetar(self) -> None:
        """Limpa o estado para uma nova operação."""
        self.cliente_atual = None
        self.input_cpf.clear()
        self.btn_entrega.hide()
        self.lbl_info.setText("Aguardando busca...")

    # --- Ações ---

    def _buscar(self) -> None:
        doc = self.input_cpf.text().strip()
        if not doc:
            return
        self.lbl_info.setText("Buscando...")
        cliente = buscar_cliente(doc)
        if cliente:
            self.cliente_atual = cliente
            self.lbl_info.setText(
                f"✔  {cliente['nome']}  —  "
                f"{cliente['rua']}, {cliente['numero']} · {cliente['bairro']}"
            )
            self.btn_entrega.show()
            self.btn_entrega.setFocus()   # operador só pressiona Enter para avançar
        else:
            self.cliente_atual = None
            self.btn_entrega.hide()
            self.lbl_info.setText("Cliente não encontrado. [F5] para cadastrar.")
            self.input_cpf.setFocus()
            self.input_cpf.selectAll()

    def _novo_cliente(self) -> None:
        if CadastroClienteDialog(parent=self).exec() == QDialog.DialogCode.Accepted:
            # Recarrega com o documento que acabou de ser digitado, se houver
            doc = self.input_cpf.text().strip()
            if doc:
                self._buscar()

    def _lancar_entrega(self) -> None:
        if not self.cliente_atual:
            return
        impressora = self.combo_impressora.currentText()
        dlg = LancarEntregaDialog(self.cliente_atual, impressora, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._esconder()    # entrega confirmada → volta para segundo plano

    def _carregar_impressoras(self) -> None:
        self.combo_impressora.clear()
        impressoras = listar_impressoras()
        if not impressoras:
            self.combo_impressora.addItem("(nenhuma impressora encontrada)")
            return
        for nome in impressoras:
            self.combo_impressora.addItem(nome)
        padrao = impressora_padrao()
        if padrao in impressoras:
            self.combo_impressora.setCurrentText(padrao)

# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # não encerra ao fechar a janela

    # Garante instância única — se já estiver rodando, avisa e sai
    _mutex = win32event.CreateMutex(None, False, "Global\\PDVEntregasGaviao")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            None, "PDV já iniciado",
            "O PDV Entregas já está rodando.\n\nPressione F10 para abrir a janela."
        )
        sys.exit(0)

    # Login obrigatório antes de qualquer coisa
    login_dlg = LoginDialog()
    if login_dlg.exec() != QDialog.DialogCode.Accepted or not login_dlg.login_ok:
        sys.exit(0)

    # Cria a janela principal já oculta
    window = PDVApp()
    # window.show() — intencionalmente omitido; F10 abre

    # Liga o sinal do hotkey global à janela
    _emitter.mostrar.connect(window._mostrar)
    _iniciar_listener_f10()

    sys.exit(app.exec())
