"""
main.py
=======
Entry point for the RPi Recorder app.

Run with:
    python3 main.py
"""

import sys
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow


def main() -> None:
    app    = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
