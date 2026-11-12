import json
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from vault.app import MainWindow
from vault.store import Store

SERVER = "PersonalVault.SingleInstance.v1"


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("falah.personalvault.windows")
        except Exception:
            pass
    paths = [os.path.abspath(a) for a in sys.argv[1:] if os.path.isfile(a)]
    app = QApplication(sys.argv)
    app.setApplicationName("Personal Vault")

    # one window only: a second launch hands its files to the first one and exits
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if sock.waitForConnected(300):
        sock.write(json.dumps(paths).encode("utf-8"))
        sock.waitForBytesWritten(1500)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(SERVER)
    server = QLocalServer()
    server.listen(SERVER)

    win = MainWindow(Store())
    win.show()

    def incoming():
        c = server.nextPendingConnection()
        if c is None:
            return
        c.waitForReadyRead(1000)
        try:
            got = json.loads(bytes(c.readAll()).decode("utf-8") or "[]")
        except Exception:
            got = []
        win.setWindowState(win.windowState() & ~0x1)  # un-minimise
        win.raise_()
        win.activateWindow()
        if got:
            QTimer.singleShot(0, lambda: win.add_files(got))

    server.newConnection.connect(incoming)
    if paths:
        QTimer.singleShot(250, lambda: win.add_files(paths))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
