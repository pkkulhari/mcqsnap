import sys
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextBrowser,
    QMessageBox,
    QInputDialog,
)
from PySide6.QtGui import QPainter, QColor, QCursor
from PySide6.QtCore import Qt, QRect, QBuffer, QIODevice, QStandardPaths

import aisuite as ai


class ConfigManager:
    """Manages application configuration and API key storage."""
    
    @staticmethod
    def get_config_dir() -> Path:
        """Get the application's configuration directory."""
        config_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    @classmethod
    def get_api_key_path(cls) -> Path:
        """Get the path to the API key file."""
        return cls.get_config_dir() / "openai_api_key.txt"

    @classmethod
    def load_api_key(cls) -> str | None:
        """Load the stored API key."""

        if os.environ.get("OPENAI_API_KEY"):
            return os.environ.get("OPENAI_API_KEY")

        api_key_path = cls.get_api_key_path()
        return api_key_path.read_text().strip() if api_key_path.exists() else None

    @classmethod
    def save_api_key(cls, api_key: str) -> None:
        """Save the API key to the configuration file."""
        api_key_path = cls.get_api_key_path()
        api_key_path.write_text(api_key)

    @classmethod
    def initialize_api_key(cls) -> str:
        """Interactively obtain and validate the API key."""
        api_key = cls.load_api_key()
        
        if not api_key:
            dialog = QInputDialog()
            dialog.setWindowTitle("OpenAI API Key")
            dialog.setLabelText("Please enter your OpenAI API key:")
            dialog.resize(400, dialog.height())
            
            if dialog.exec() == QInputDialog.Accepted:
                api_key = dialog.textValue()
            else:
                api_key = ""
            
            if not api_key:
                QMessageBox.critical(None, "Error", "OpenAI API key is required to use this application.")
                sys.exit(1)
                
            cls.save_api_key(api_key)
        
        return api_key


class AIHelper:
    """Helper class for AI interactions."""
    
    def __init__(self, model: str = "openai:gpt-4o-mini", api_key: str = None):
        self.model = model
        self.client = ai.Client({'openai': {'api_key': api_key}})
        self.system_message = {
            "role": "system",
            "content": (
                "You are an expert in solving multiple-choice questions (MCQs). The user will provide an image containing an MCQ. "
                "Your task is to extract the question and options, then identify and return the correct option in the following format:\n\n"
                "Question: [Extracted question]\n"
                "A or 1: [Option A or option 1]\n"
                "B or 2: [Option B or option 2]\n"
                "C or 3: [Option C or option 3]\n"
                "D or 4: [Option D or option 4]\n\n"
                "Correct Option: **[Letter or number of the correct option] ([Correct option text])**\n"
            ),
        }

    def analyze_mcq(self, image_base64_url: str) -> str:
        """Analyze the multiple-choice question image."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    self.system_message,
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": image_base64_url},
                            }
                        ],
                    },
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"AI analysis failed: {e}")


class ResponseWindow(QWidget):
    """Window to display AI response."""
    
    def __init__(self, response_text: str):
        super().__init__()        
        self.setWindowTitle("Answer")
        self.setGeometry(100, 100, 600, 400)

        layout = QVBoxLayout()

        response_text_browser = QTextBrowser()
        response_text_browser.setOpenExternalLinks(True)
        response_text_browser.setMarkdown(response_text)
        response_text_browser.setStyleSheet("QTextBrowser { padding: 10px; }")

        layout.addWidget(response_text_browser)
        self.setLayout(layout)


class ScreenshotWindow(QMainWindow):
    """Main window for screenshot selection and processing."""
    
    def __init__(self, ai_helper: AIHelper):
        super().__init__()
        self.ai_helper = ai_helper
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.showFullScreen()

        screen = QApplication.primaryScreen()
        self.pixmap = screen.grabWindow(0)

        self.selection_started = False
        self.start_pos = None
        self.end_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selection_started = True
            self.start_pos = event.pos()
            self.end_pos = self.start_pos

    def mouseMoveEvent(self, event):
        if self.selection_started:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.selection_started:
            self.selection_started = False
            self.process_screenshot()
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)

        overlay_color = QColor(0, 0, 0, 100)
        painter.fillRect(self.rect(), overlay_color)

        cursor = self.cursor()
        cursor.setShape(Qt.CrossCursor)
        self.setCursor(cursor)

        if self.start_pos and self.end_pos:
            selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            painter.drawPixmap(selection_rect, self.pixmap, selection_rect)

            pen = painter.pen()
            pen.setColor(Qt.white)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(selection_rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def process_screenshot(self):
        if self.start_pos and self.end_pos:
            QApplication.setOverrideCursor(Qt.WaitCursor)

            selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            cropped_pixmap = self.pixmap.copy(selection_rect)

            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            cropped_pixmap.save(buffer, "PNG")
            image_base64 = buffer.data().toBase64().data().decode("utf-8")
            image_base64_url = f"data:image/png;base64,{image_base64}"

            try:
                response_text = self.ai_helper.analyze_mcq(image_base64_url)
                QApplication.restoreOverrideCursor()

                self.response_window = ResponseWindow(response_text)
                self.response_window.show()

            except Exception as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(self, "Error", str(e))

            self.close()


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)

    api_key = ConfigManager.initialize_api_key()
    ai_helper = AIHelper(api_key=api_key)    
    window = ScreenshotWindow(ai_helper)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()