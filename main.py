import io
import json
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextBrowser,
    QMessageBox,
    QInputDialog,
    QGraphicsDropShadowEffect,
    QLabel,
)
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import Qt, QRect, QPoint, QBuffer, QIODevice, QStandardPaths, Signal
from google import genai

CONFIG_PATH = (
    Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
    / "mcqsnap"
    / "config.json"
)

SYSTEM_PROMPT = """You are an MCQ solver. Analyze the image and identify the question and correct answer.
Format your response as:
**Question:** [The question text]

**Answer:** [Option number]) [Answer text]
"""


def load_api_key() -> str | None:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text()).get("api_key")
    return None


def save_api_key(api_key: str):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"api_key": api_key}))


def get_api_key() -> str:
    api_key = load_api_key()
    if api_key:
        return api_key

    dialog = QInputDialog()
    dialog.setWindowTitle("MCQSnap - API Key")
    dialog.setLabelText("Enter your Gemini API key:")
    dialog.resize(450, 150)

    if dialog.exec() == QInputDialog.Accepted and dialog.textValue().strip():
        api_key = dialog.textValue().strip()
        save_api_key(api_key)
        return api_key

    QMessageBox.critical(None, "Error", "API key is required.")
    sys.exit(1)


def analyze_image(client: genai.Client, image_data: bytes) -> str:
    image = Image.open(io.BytesIO(image_data))
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[SYSTEM_PROMPT, image],
    )
    return response.text


def choose_mode() -> str:
    dialog = QMessageBox()
    dialog.setWindowTitle("MCQSnap - Select Mode")
    dialog.setText("Choose how you want to capture questions.")
    manual_button = dialog.addButton("Manual Mode", QMessageBox.AcceptRole)
    auto_button = dialog.addButton("Auto Mode", QMessageBox.AcceptRole)
    dialog.setDefaultButton(manual_button)
    dialog.exec()

    clicked = dialog.clickedButton()
    if clicked == manual_button:
        return "manual"
    if clicked == auto_button:
        return "auto"

    sys.exit(0)


class ResponseWindow(QWidget):
    def __init__(self, text: str):
        super().__init__()
        self.setWindowTitle("MCQSnap - Answer")
        self.resize(520, 360)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.center_on_screen()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        browser = QTextBrowser()
        browser.setStyleSheet("font-size: 16px;")
        browser.setMarkdown(text)
        browser.setOpenExternalLinks(True)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(99, 102, 241, 80))
        shadow.setOffset(0, 4)
        browser.setGraphicsEffect(shadow)

        layout.addWidget(browser)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.close()
        elif event.key() == Qt.Key_Escape:
            QApplication.quit()

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(geometry.center())
        self.move(frame.topLeft())


class SelectionWindow(QMainWindow):
    selection_made = Signal(QRect, bytes)
    selection_canceled = Signal()

    def __init__(self):
        super().__init__()
        self.start_pos = self.end_pos = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.showFullScreen()
        self.setCursor(Qt.CrossCursor)
        self.pixmap = QApplication.primaryScreen().grabWindow(0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = self.end_pos = event.pos()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_pos:
            self.process_selection()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.selection_canceled.emit()
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self.start_pos and self.end_pos:
            rect = QRect(self.start_pos, self.end_pos).normalized()
            painter.drawPixmap(rect, self.pixmap, rect)

            pen = painter.pen()
            pen.setColor(QColor(99, 102, 241))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(rect)

            # Draw dimensions
            painter.setFont(QFont("Segoe UI", 10))
            painter.setPen(QColor(255, 255, 255, 200))
            painter.drawText(
                rect.bottomRight() + QPoint(-60, 20),
                f"{rect.width()} × {rect.height()}",
            )

    def process_selection(self):
        if not self.start_pos or not self.end_pos:
            return

        rect = QRect(self.start_pos, self.end_pos).normalized()
        if rect.width() < 10 or rect.height() < 10:
            self.close()
            return

        cropped = self.pixmap.copy(rect)

        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        cropped.save(buffer, "PNG")

        self.selection_made.emit(rect, bytes(buffer.data()))
        self.close()


class ManualController(QWidget):
    def __init__(self, client: genai.Client):
        super().__init__()
        self.client = client
        self.selection_window: SelectionWindow | None = None
        self.response_window: ResponseWindow | None = None

    def start(self):
        self.selection_window = SelectionWindow()
        self.selection_window.selection_made.connect(self.handle_selection)
        self.selection_window.selection_canceled.connect(QApplication.quit)
        self.selection_window.show()

    def handle_selection(self, rect: QRect, image_bytes: bytes):
        self.selection_window = None
        self.run_analysis(image_bytes)

    def run_analysis(self, image_bytes: bytes):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            response = analyze_image(self.client, image_bytes)
            self.response_window = ResponseWindow(response)
            self.response_window.show()
        except Exception as e:
            QMessageBox.critical(None, "Error", str(e))
        finally:
            QApplication.restoreOverrideCursor()


class AutoController(QWidget):
    def __init__(self, client: genai.Client):
        super().__init__()
        self.client = client
        self.fixed_rect: QRect | None = None
        self.selection_window: SelectionWindow | None = None
        self.response_window: ResponseWindow | None = None
        self.processing = False
        self.busy_overlay: QWidget | None = None

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)

        label = QLabel("Auto Mode\nEnter: capture / close answer\nEsc: exit")
        label.setStyleSheet(
            "color: white; font-size: 13px; background-color: rgba(17, 24, 39, 210);"
            " padding: 10px; border-radius: 10px; border: 1px solid rgba(99,102,241,0.6);"
        )
        layout.addWidget(label)

    def start(self):
        QMessageBox.information(
            None,
            "MCQSnap - Auto Mode",
            "Select a fixed capture area for auto mode.\nPress Esc to cancel.",
        )
        self.selection_window = SelectionWindow()
        self.selection_window.selection_made.connect(self.on_area_selected)
        self.selection_window.selection_canceled.connect(QApplication.quit)
        self.selection_window.show()

    def on_area_selected(self, rect: QRect, _: bytes):
        self.fixed_rect = rect
        self.selection_window = None
        self.show()
        self.raise_()
        self.activateWindow()
        self.grabKeyboard()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.response_window and self.response_window.isVisible():
                self.response_window.close()
                self.response_window = None
                return
            if not self.processing and self.fixed_rect:
                self.capture_and_analyze()
        elif event.key() == Qt.Key_Escape:
            QApplication.quit()

    def show_busy_overlay(self):
        if self.busy_overlay:
            return
        overlay = QWidget()
        overlay.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        overlay.setAttribute(Qt.WA_TranslucentBackground)
        overlay.setCursor(Qt.BusyCursor)
        overlay.showFullScreen()
        overlay.raise_()
        overlay.activateWindow()
        self.busy_overlay = overlay
        QApplication.setOverrideCursor(Qt.BusyCursor)
        QApplication.processEvents()

    def hide_busy_overlay(self):
        if self.busy_overlay:
            self.busy_overlay.close()
            self.busy_overlay = None
        QApplication.restoreOverrideCursor()
        QApplication.processEvents()

    def capture_and_analyze(self):
        if not self.fixed_rect:
            return

        self.processing = True
        self.hide()
        QApplication.processEvents()

        try:
            pixmap = QApplication.primaryScreen().grabWindow(0)
            cropped = pixmap.copy(self.fixed_rect)
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            cropped.save(buffer, "PNG")

            self.show()
            self.raise_()
            self.activateWindow()
            self.grabKeyboard()

            self.show_busy_overlay()
            response: str | None = None
            try:
                response = analyze_image(self.client, bytes(buffer.data()))
            finally:
                self.hide_busy_overlay()

            if response:
                self.response_window = ResponseWindow(response)
                self.response_window.show()
        except Exception as e:
            QMessageBox.critical(None, "Error", str(e))
        finally:
            self.processing = False
            if not self.isVisible():
                self.show()
            self.raise_()
            self.activateWindow()
            self.grabKeyboard()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    mode = choose_mode()
    api_key = get_api_key()
    client = genai.Client(api_key=api_key)

    if mode == "manual":
        controller = ManualController(client)
        controller.start()
    else:
        app.setQuitOnLastWindowClosed(False)
        controller = AutoController(client)
        controller.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
