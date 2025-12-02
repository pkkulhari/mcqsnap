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
)
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import Qt, QRect, QPoint, QBuffer, QIODevice, QStandardPaths
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


class ResponseWindow(QWidget):
    def __init__(self, text: str):
        super().__init__()
        self.setWindowTitle("MCQSnap - Answer")
        self.setGeometry(100, 100, 650, 450)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        browser = QTextBrowser()
        browser.setMarkdown(text)
        browser.setOpenExternalLinks(True)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(99, 102, 241, 80))
        shadow.setOffset(0, 4)
        browser.setGraphicsEffect(shadow)

        layout.addWidget(browser)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


class ScreenshotWindow(QMainWindow):
    def __init__(self, client: genai.Client):
        super().__init__()
        self.client = client
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

        QApplication.setOverrideCursor(Qt.WaitCursor)
        cropped = self.pixmap.copy(rect)

        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        cropped.save(buffer, "PNG")

        try:
            response = analyze_image(self.client, buffer.data().data())
            QApplication.restoreOverrideCursor()
            self.response_window = ResponseWindow(response)
            self.response_window.show()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(None, "Error", str(e))

        self.close()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    api_key = get_api_key()
    client = genai.Client(api_key=api_key)

    window = ScreenshotWindow(client)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
