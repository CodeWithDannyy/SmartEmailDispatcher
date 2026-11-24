import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from ui.compose_window import ComposeWindow
from ui.login_window import LoginWindow
from ui.styles import STYLESHEET


class App:
    def __init__(self) -> None:
        self.login = LoginWindow()
        self.login.logged_in.connect(self.open_compose)
        self.compose = None

    def start(self) -> None:
        self.login.show()

    def open_compose(self, config, credentials) -> None:
        self.compose = ComposeWindow(config, credentials)
        self.compose.logged_out.connect(self.back_to_login)
        self.compose.show()
        self.login.hide()

    def back_to_login(self, email: str) -> None:
        self.compose = None
        self.login.reset_for_logout(email)
        self.login.show()


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Smart Email Dispatcher")
    app.setStyleSheet(STYLESHEET)
    controller = App()
    controller.start()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
