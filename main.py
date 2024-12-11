import sys
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextBrowser,
    QMessageBox,
)
from PySide6.QtGui import QPainter, QColor, QCursor
from PySide6.QtCore import Qt, QRect, QBuffer, QByteArray, QIODevice
import aisuite as ai

client = ai.Client()
model = "openai:gpt-4o-mini"
system_message = {
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


class ResponseWindow(QWidget):
    def __init__(self, response_text):
        super().__init__()
        self.setWindowTitle("Answer")
        self.setGeometry(100, 100, 600, 400)

        layout = QVBoxLayout()

        # Create text browser for response with markdown support
        response_text_browser = QTextBrowser()
        response_text_browser.setOpenExternalLinks(True)
        response_text_browser.setMarkdown(response_text)
        response_text_browser.setStyleSheet("QTextBrowser { padding: 10px; }")

        layout.addWidget(response_text_browser)
        self.setLayout(layout)


class ScreenshotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.showFullScreen()

        # Capture the entire screen
        screen = QApplication.primaryScreen()
        self.pixmap = screen.grabWindow(0)

        # Selection variables
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

        # Draw the screen capture as the background
        painter.drawPixmap(self.rect(), self.pixmap)

        # Create a semi-transparent overlay for non-selected areas
        overlay_color = QColor(0, 0, 0, 100)
        painter.fillRect(self.rect(), overlay_color)

        # Set cursor to crosshair
        cursor = self.cursor()
        cursor.setShape(Qt.CrossCursor)
        self.setCursor(cursor)

        # Draw the selection rectangle if selection is in progress
        if self.start_pos and self.end_pos:
            selection_rect = QRect(self.start_pos, self.end_pos).normalized()

            # Clear the overlay from selected area by drawing the original pixmap portion
            painter.drawPixmap(selection_rect, self.pixmap, selection_rect)

            # Draw rectangle border
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
            # Show loading cursor
            QApplication.setOverrideCursor(Qt.WaitCursor)

            selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            cropped_pixmap = self.pixmap.copy(selection_rect)

            # Convert QPixmap to base64 image URL
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            cropped_pixmap.save(buffer, "PNG")
            image_base64 = buffer.data().toBase64().data().decode("utf-8")
            image_base64_url = f"data:image/png;base64,{image_base64}"

            try:
                # Ask AI
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        system_message,
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

                # Restore cursor
                QApplication.restoreOverrideCursor()

                # Show response in new window
                response_text = response.choices[0].message.content
                self.response_window = ResponseWindow(response_text)
                self.response_window.show()

            except Exception as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

            self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScreenshotWindow()
    window.show()
    sys.exit(app.exec())
