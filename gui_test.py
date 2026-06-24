import sys
import os
import re
import json
import random
import ast
import unicodedata
from pathlib import Path

# Load .env file BEFORE importing anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
    print(f"[DEBUG] .env loaded. API_KEY={'set' if os.environ.get('UNLIMITED_API_KEY') else 'NOT SET'}")
except ImportError:
    print("[WARNING] python-dotenv not installed. Install with: pip install python-dotenv")
    pass

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QFrame, QSizePolicy, QCompleter, 
    QInputDialog, QMenu, QDialog, QComboBox, QFormLayout, QDialogButtonBox, QAction,
    QListWidget, QListWidgetItem, QFileDialog, QTextBrowser, QScrollArea,
    QGraphicsOpacityEffect, QTreeView, QHeaderView, QAbstractItemView, QSplitter,
    QPlainTextEdit
)
from PyQt5.QtWidgets import QFileSystemModel as _QFileSystemModel
from PyQt5.QtGui import QIcon, QFont, QColor, QPalette, QPixmap, QTextCursor, QMovie, QSyntaxHighlighter, QTextCharFormat
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer, QPropertyAnimation, QEasingCurve, QModelIndex, QUrl, QStringListModel
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

# Adjust import path if needed to import from unlimited_code
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import unlimited_code
    from unlimited_code import (
        UnlimitedClient, UnlimitedCodeApp, AVAILABLE_MODELS, THEMES, DEFAULT_MODEL,
        get_theme
    )
except ImportError as e:
    print(f"Error importing from unlimited_code: {e}")
    sys.exit(1)

# ЖЕСТКО ЗАШИТЫЕ СИСТЕМНЫЕ ПРАВИЛА (НЕИЗМЕНЯЕМЫЕ)
HARDCODED_SYSTEM_RULES = """Rules:
1. You have full capability to read files, folder structures, and system state.
2. You have full capability to create new files, directories, and project structures.
3. You have full capability to modify existing files, directories, and architectures.
4. You have full capability to permanently delete files, directories, and project structures.
5. ALWAYS prefer using tools when you need to read, write, or inspect project files.
6. Paths are relative to the project root. Do not use absolute paths.
7. When writing files, provide the FULL final content. Do not truncate.
8. If a command is destructive, ask the user for confirmation before running it.
9. Think step by step. Use multiple tool calls if needed.
10. When done, give a final answer in plain text.
11. Use only the tools listed above. Unknown tools will return an error.
12. Keep your final answer concise but complete.
13. If asked to create or edit a file, YOU MUST use the write_file tool.
14. When using write_file, provide the COMPLETE final file content.
15. If the user says "create file X", they want the content saved to X.
16. NEVER forget what you did several requests ago and what is in the files you have already viewed or created.
17. ABSOLUTELY NEVER TRUNCATE OR CUT OFF FILE CONTENTS. Always provide the complete file from the first to the last line."""

def _load_global_settings() -> dict:
    try:
        settings_file = Path.home() / ".unlimited_code" / "global_settings.json"
        if settings_file.exists():
            return json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_global_settings(settings: dict):
    try:
        settings_dir = Path.home() / ".unlimited_code"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = settings_dir / "global_settings.json"
        settings_file.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Error saving settings: {e}")

def _load_prompt_history() -> list:
    try:
        f = Path.home() / ".unlimited_code" / "prompt_history.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_prompt_history(history: list):
    try:
        d = Path.home() / ".unlimited_code"
        d.mkdir(parents=True, exist_ok=True)
        (d / "prompt_history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def clean_binary_text(text):
    """Автодекодер: очищает текст от бинарного кода, непечатных символов и декодирует b'...'"""
    if isinstance(text, bytes):
        try:
            text = text.decode('utf-8')
        except Exception:
            text = text.decode('latin-1', errors='ignore')
            
    stripped = text.strip()
    if (stripped.startswith("b'") and stripped.endswith("'")) or (stripped.startswith('b"') and stripped.endswith('"')):
        try:
            actual_bytes = ast.literal_eval(stripped)
            if isinstance(actual_bytes, bytes):
                text = actual_bytes.decode('utf-8', errors='replace')
        except Exception:
            pass
            
    cleaned_chars = []
    for c in text:
        if c in ['\n', '\t', '\r']:
            cleaned_chars.append(c)
        elif unicodedata.category(c)[0] == 'C':  # Удаляем непечатные управляющие символы
            continue
        else:
            cleaned_chars.append(c)
    return ''.join(cleaned_chars)

class StdoutRedirector(QThread):
    text_written = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

    def write(self, text):
        clean_text = ANSI_ESCAPE_PATTERN.sub('', text)
        clean_text = clean_binary_text(clean_text)
        self.text_written.emit(clean_text)
        try:
            if self.original_stdout:
                self.original_stdout.write(text)
                self.original_stdout.flush()
        except Exception:
            pass

    def flush(self):
        try:
            if self.original_stdout:
                self.original_stdout.flush()
        except Exception:
            pass

class AgentWorker(QThread):
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, client, user_input, system_instruction=""):
        super().__init__()
        self.client = client
        self.user_input = user_input
        self.system_instruction = system_instruction
        self._stopped = False

    def run(self):
        try:
            prompt = self.user_input
            
            # Формируем полную системную инструкцию: ЖЕСТКИЕ ПРАВИЛА + инструкции пользователя
            full_instruction = HARDCODED_SYSTEM_RULES
            if self.system_instruction:
                full_instruction += "\n\nAdditional User Instructions:\n" + self.system_instruction
            
            # Пробуем задать как атрибут
            if hasattr(self.client, 'system_instruction'):
                self.client.system_instruction = full_instruction
            if hasattr(self.client, 'system_prompt'):
                self.client.system_prompt = full_instruction
            
            # Фоллбэк: добавляем инструкцию прямо в текст запроса
            prompt = f"System: {full_instruction}\n\nUser: {self.user_input}"
            
            self.client.chat(prompt)
            
        except Exception as e:
            if not self._stopped:
                self.error_occurred.emit(str(e))
        finally:
            self.finished.emit()
    
    def stop(self):
        self._stopped = True
        self.terminate()

class MockSession:
    def __init__(self, parent_gui):
        self.parent_gui = parent_gui
    
    def prompt(self, text, **kwargs):
        clean_text = str(text)
        if hasattr(text, 'value'): 
            clean_text = text.value
        val, ok = QInputDialog.getText(self.parent_gui, "Input Required", clean_text)
        return val if (ok and val) else ""

class ChatHistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_gui = parent
        self.setWindowTitle("💬 Chat History")
        self.resize(700, 500)
        
        # Fade in animation
        self.setWindowOpacity(0.0)
        
        # Apply theme
        if parent:
            bg = parent.theme.background
            fg = parent.theme.text_fg
            accent = getattr(parent.theme, "accent", "#61afef")
            prompt_bg = getattr(parent.theme, "prompt_bg", "#3e4451")
            
            self.setStyleSheet(f"""
                QDialog {{
                    background-color: {bg};
                    color: {fg};
                }}
                QLabel {{
                    color: {fg};
                }}
                QListWidget {{
                    background-color: {prompt_bg};
                    color: {fg};
                    border: 2px solid {accent};
                    border-radius: 8px;
                    padding: 8px;
                    font-size: 12px;
                }}
                QListWidget::item {{
                    padding: 12px;
                    border-radius: 6px;
                    margin: 4px;
                }}
                QListWidget::item:hover {{
                    background-color: #4e5461;
                }}
                QListWidget::item:selected {{
                    background-color: {accent};
                    color: {bg};
                }}
                QPushButton {{
                    background-color: {accent};
                    color: {bg};
                    border: none;
                    border-radius: 6px;
                    padding: 10px 20px;
                    font-weight: bold;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {accent};
                    opacity: 0.9;
                }}
            """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("💬 Recent Chats")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        layout.addWidget(title)
        
        # Chat list
        self.chat_list = QListWidget()
        self.chat_list.itemDoubleClicked.connect(self._switch_chat)
        layout.addWidget(self.chat_list)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_switch = QPushButton("✓ Open")
        self.btn_switch.clicked.connect(self._switch_chat)
        self.btn_switch.setFixedWidth(100)
        
        self.btn_rename = QPushButton("✎ Rename")
        self.btn_rename.clicked.connect(self._rename_chat)
        self.btn_rename.setFixedWidth(100)
        
        self.btn_delete = QPushButton("🗑 Delete")
        self.btn_delete.clicked.connect(self._delete_chat)
        self.btn_delete.setFixedWidth(100)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setFixedWidth(100)
        
        btn_layout.addWidget(self.btn_switch)
        btn_layout.addWidget(self.btn_rename)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)
        
        self._load_chats()
        
        # Start fade in animation
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(250)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade_animation.start()
    
    def _load_chats(self):
        self.chat_list.clear()
        if not hasattr(self.parent_gui, 'app_instance'):
            return
        
        try:
            chats = self.parent_gui.app_instance.chat_store.list_chats()
            for chat_meta in chats:
                chat_id = chat_meta.get("id", "")
                name = chat_meta.get("name", "Unnamed")
                updated = chat_meta.get("updated_at", "")
                msg_count = chat_meta.get("messages", 0)
                preview = chat_meta.get("preview", "")
                
                display_text = f"{name} ({msg_count} msgs) - {updated[:16]}"
                if preview:
                    display_text += f"\n  {preview}"
                
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, chat_id)
                self.chat_list.addItem(item)
        except Exception as e:
            print(f"Error loading chats: {e}")
    
    def _switch_chat(self):
        selected = self.chat_list.currentItem()
        if not selected:
            return
        chat_id = selected.data(Qt.UserRole)
        try:
            self.parent_gui.app_instance._switch_chat(chat_id)
            print(f"\n[System] Switched to chat: {selected.text().split('(')[0].strip()}")
            self.accept()
        except Exception as e:
            print(f"Error switching chat: {e}")
    
    def _rename_chat(self):
        selected = self.chat_list.currentItem()
        if not selected:
            return
        chat_id = selected.data(Qt.UserRole)
        new_name, ok = QInputDialog.getText(self, "Rename Chat", "Enter new name:")
        if ok and new_name.strip():
            try:
                self.parent_gui.app_instance.chat_store.rename(chat_id, new_name.strip())
                self._load_chats()
                print(f"\n[System] Chat renamed to: {new_name.strip()}")
            except Exception as e:
                print(f"Error renaming chat: {e}")
    
    def _delete_chat(self):
        selected = self.chat_list.currentItem()
        if not selected:
            return
        chat_id = selected.data(Qt.UserRole)
        try:
            self.parent_gui.app_instance.chat_store.delete(chat_id)
            self._load_chats()
            print(f"\n[System] Chat deleted")
        except Exception as e:
            print(f"Error deleting chat: {e}")


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Settings")
        self.resize(500, 400)
        
        # Fade in animation
        self.setWindowOpacity(0.0)
        
        # Apply theme colors
        if parent:
            bg = parent.theme.background
            fg = parent.theme.text_fg
            accent = getattr(parent.theme, "accent", "#61afef")
            prompt_bg = getattr(parent.theme, "prompt_bg", "#3e4451")
            
            self.setStyleSheet(f"""
                QDialog {{
                    background-color: {bg};
                    color: {fg};
                }}
                QLabel {{
                    color: {fg};
                    font-size: 14px;
                    font-weight: bold;
                }}
                QComboBox {{
                    background-color: {prompt_bg};
                    color: {fg};
                    border: 2px solid {accent};
                    border-radius: 8px;
                    padding: 10px;
                    font-size: 13px;
                }}
                QComboBox:hover {{
                    border: 3px solid {accent};
                    background-color: #4e5461;
                }}
                QComboBox::drop-down {{
                    border: none;
                    width: 35px;
                }}
                QComboBox::down-arrow {{
                    image: none;
                    border-left: 6px solid transparent;
                    border-right: 6px solid transparent;
                    border-top: 6px solid {fg};
                    margin-right: 10px;
                }}
                QComboBox QAbstractItemView {{
                    background-color: {prompt_bg};
                    color: {fg};
                    selection-background-color: {accent};
                    border: 2px solid {accent};
                    border-radius: 8px;
                    padding: 6px;
                }}
                QPushButton {{
                    background-color: #2ecc71;
                    color: white;
                    border: 3px solid #27ae60;
                    border-radius: 8px;
                    padding: 12px 25px;
                    font-weight: bold;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background-color: #27ae60;
                    color: white;
                    border: 3px solid #229954;
                }}
                QPushButton#cancelBtn {{
                    background-color: #e74c3c;
                    color: white;
                    border: 3px solid #c0392b;
                }}
                QPushButton#cancelBtn:hover {{
                    background-color: #c0392b;
                    color: white;
                    border: 3px solid #a93226;
                }}
            """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(25)
        self.layout.setContentsMargins(25, 25, 25, 25)
        
        # Title
        title = QLabel("⚙️ Preferences")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.layout.addWidget(title)
        
        # Form layout
        form_layout = QFormLayout()
        form_layout.setSpacing(18)
        form_layout.setLabelAlignment(Qt.AlignLeft)
        
        # Theme selector
        theme_label = QLabel("🎨 Theme:")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.setCurrentText(parent.theme.name if parent else "dracula")
        form_layout.addRow(theme_label, self.theme_combo)
        
        # Font selector
        font_label = QLabel("🔤 Font Family:")
        self.font_combo = QComboBox()
        self.font_combo.addItems([
            "Consolas",             # Classic monospace
            "Courier New",          # Traditional typewriter
            "Lucida Console",       # Clean monospace
            "Fira Code",           # Modern with ligatures
            "Cascadia Code",       # Microsoft modern
            "JetBrains Mono",      # Developer favorite
            "Source Code Pro",     # Adobe professional
            "Monaco",              # Mac classic
            "Menlo",               # Mac modern
            "DejaVu Sans Mono",    # Open source classic
            "Ubuntu Mono",         # Ubuntu style
            "Inconsolata",         # Minimalist
            "Anonymous Pro",       # Coding focused
            "Hack",                # Sharp and clear
            "Roboto Mono",         # Google modern
            "IBM Plex Mono",       # IBM corporate
            "SF Mono",             # Apple San Francisco
            "Comic Sans MS",       # Fun/casual
            "Arial",               # Sans-serif standard
            "Verdana",             # Web-safe readable
            "Trebuchet MS",        # Humanist sans
            "Georgia",             # Elegant serif
            "Times New Roman",     # Classic serif
            "Impact",              # Bold display
            "Courier",             # Original typewriter
            "Lucida Sans",         # Humanist sans
            "Tahoma",              # Microsoft classic
            "Century Gothic",      # Geometric sans
            "Palatino",            # Old-style serif
            "Garamond",            # Renaissance serif
        ])
        current_font = parent.font_family if parent else "Consolas"
        if current_font in [self.font_combo.itemText(i) for i in range(self.font_combo.count())]:
            self.font_combo.setCurrentText(current_font)
        else:
            self.font_combo.setCurrentText("Consolas")
        form_layout.addRow(font_label, self.font_combo)
        
        # Font size selector
        size_label = QLabel("📏 Font Size:")
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems(["6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "18", "20", "22", "24"])
        current_size = str(parent.font_size if parent else 11)
        if current_size in [self.font_size_combo.itemText(i) for i in range(self.font_size_combo.count())]:
            self.font_size_combo.setCurrentText(current_size)
        else:
            self.font_size_combo.setCurrentText("11")
        form_layout.addRow(size_label, self.font_size_combo)
        
        # Reasoning Effort selector
        reasoning_label = QLabel("🧠 Reasoning Effort:")
        self.reasoning_combo = QComboBox()
        self.reasoning_combo.addItems(["Default", "Low", "Medium", "High"])
        current_reasoning = parent.reasoning_effort if parent else "Default"
        self.reasoning_combo.setCurrentText(current_reasoning)
        form_layout.addRow(reasoning_label, self.reasoning_combo)
        
        self.layout.addLayout(form_layout)
        
        # System instruction
        instruction_label = QLabel("📝 System Instruction:")
        self.layout.addWidget(instruction_label)
        
        self.instruction_edit = QPlainTextEdit()
        self.instruction_edit.setPlaceholderText("Custom instructions for the AI (e.g. 'Always respond in Russian', 'Use concise code')...")
        self.instruction_edit.setMaximumHeight(120)
        self.instruction_edit.setMinimumHeight(80)
        current_instruction = ""
        if parent:
            current_instruction = getattr(parent, 'system_instruction', '') or ''
        self.instruction_edit.setPlainText(current_instruction)
        
        if parent:
            bg = parent.theme.background
            fg = parent.theme.text_fg
            accent = getattr(parent.theme, "accent", "#61afef")
            prompt_bg = getattr(parent.theme, "prompt_bg", "#3e4451")
            self.instruction_edit.setStyleSheet(f"""
                QPlainTextEdit {{
                    background-color: {prompt_bg};
                    color: {fg};
                    border: 2px solid {accent};
                    border-radius: 8px;
                    padding: 10px;
                    font-size: 12px;
                    font-family: Consolas;
                }}
                QPlainTextEdit:focus {{
                    border: 3px solid {accent};
                }}
            """)
        self.layout.addWidget(self.instruction_edit)
        
        self.layout.addStretch()
        
        # Buttons — compact
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.clicked.connect(self._animated_reject)
        self.cancel_btn.setFixedSize(100, 28)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(self.cancel_btn)
        
        self.ok_btn = QPushButton("✓ Apply")
        self.ok_btn.clicked.connect(self._animated_accept)
        self.ok_btn.setFixedSize(100, 28)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(self.ok_btn)
        
        self.layout.addLayout(button_layout)
        
        # Start fade in animation
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(250)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade_animation.start()
    
    def _animated_accept(self):
        """Fade out then accept."""
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.finished.connect(self.accept)
        anim.start()
        self._close_anim = anim
    
    def _animated_reject(self):
        """Fade out then reject."""
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.finished.connect(self.reject)
        anim.start()
        self._close_anim = anim

class CustomConsoleGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Unlimited Code IDE")
        self.resize(1100, 750)
        
        # Window opening animation - fade in
        self.setWindowOpacity(0.0)
        
        # Load theme from settings
        settings = _load_global_settings()
        theme_name = settings.get("theme", "dracula")
        self.theme = get_theme(theme_name)
        self.model_alias = settings.get("model", "claude-opus-4.8")
        self.font_family = settings.get("font_family", "Consolas")
        self.font_size = settings.get("font_size", 11)
        self.reasoning_effort = settings.get("reasoning_effort", "Default")
        
        self.project_folder = Path(settings.get("project", str(Path.cwd())))
        self.system_instruction = settings.get("system_instruction", "")
        self.api_key = os.environ.get("UNLIMITED_API_KEY", "dummy")
        
        self.client = UnlimitedClient(api_key=self.api_key, model=self.model_alias, project_folder=self.project_folder)
        
        # Apply reasoning effort if client supports it
        if self.reasoning_effort != "Default":
            effort_val = self.reasoning_effort.lower()
            if hasattr(self.client, 'reasoning_effort'):
                self.client.reasoning_effort = effort_val
            if hasattr(self.client, 'thinking'):
                self.client.thinking = effort_val
            if hasattr(self.client, 'effort'):
                self.client.effort = effort_val
        
        # Initialize the app engine to handle commands natively
        self.app_instance = UnlimitedCodeApp(self.project_folder, self.model_alias)
        self.app_instance.client = self.client
        self.app_instance.session = MockSession(self)
        
        # Thinking animation timer
        self.thinking_phrases = ["Thinking", "Analyzing", "Working", "Generating", "Processing"]
        self.thinking_index = 0
        self.thinking_timer = QTimer(self)
        self.thinking_timer.timeout.connect(self._update_thinking_label)
        
        self.is_generating = False
        self.worker = None
        
        # ИСТОРИЯ ВВОДА (для стрелок вверх/вниз)
        self.prompt_history = _load_prompt_history()
        self.history_index = -1
        
        self._setup_ui()
        self._apply_theme()
        
        self.redirector = StdoutRedirector()
        self.redirector.text_written.connect(self._append_text)
        sys.stdout = self.redirector
        sys.stderr = self.redirector
        
        # Redirect rich console output used by the app commands
        unlimited_code.console.file = self.redirector

        self._set_api_status("idle")
        
        # Fade in animation for window opening
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(600)  # 600ms smooth fade
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.fade_animation.start()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QHBoxLayout(central_widget) # Horizontal: Sidebar + Main Area
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # LEFT SIDEBAR - HUGE ICONS
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(180)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(15, 35, 15, 35)
        self.sidebar_layout.setSpacing(40)
        
        assets_dir = Path(__file__).parent / "assets"
        
        # Sidebar Buttons with HUGE icons (2x bigger)
        self.btn_newchat = QPushButton()
        self.btn_newchat.setToolTip("New Chat (/newchat)")
        if (assets_dir / "newchat.png").exists(): 
            self.btn_newchat.setIcon(QIcon(str(assets_dir / "newchat.png")))
        else: 
            self.btn_newchat.setText("N")
        self.btn_newchat.clicked.connect(lambda: self._execute_command("/newchat"))
        
        self.btn_history = QPushButton()
        self.btn_history.setToolTip("Chat History (/chats)")
        if (assets_dir / "history.png").exists(): 
            self.btn_history.setIcon(QIcon(str(assets_dir / "history.png")))
        else: 
            self.btn_history.setText("H")
        self.btn_history.clicked.connect(self._open_history)
        
        self.btn_files = QPushButton()
        self.btn_files.setToolTip("File Options")
        if (assets_dir / "files.png").exists(): 
            self.btn_files.setIcon(QIcon(str(assets_dir / "files.png")))
        else: 
            self.btn_files.setText("F")
        
        # File dropdown menu
        self.file_menu = QMenu(self)
        self.file_menu.setStyleSheet("""
            QMenu { 
                background-color: #282c34; 
                color: #abb2bf; 
                border: 2px solid #3e4451; 
                border-radius: 8px; 
                padding: 8px; 
            }
            QMenu::item { 
                padding: 12px 36px; 
                border-radius: 6px; 
                font-size: 14px; 
            }
            QMenu::item:selected { 
                background-color: #3e4451; 
                color: #ffffff; 
            }
        """)
        action_folder = self.file_menu.addAction("Select Folder")
        action_file = self.file_menu.addAction("Select File")
        self.file_menu.addSeparator()
        action_quit = self.file_menu.addAction("Quit")
        
        action_folder.triggered.connect(self._select_folder)
        action_file.triggered.connect(lambda: print("[Info] Select File feature coming soon..."))
        action_quit.triggered.connect(self.close)
        
        self.btn_files.setMenu(self.file_menu)
        
        # HUGE sidebar buttons
        for btn in [self.btn_newchat, self.btn_history, self.btn_files]:
            btn.setFixedSize(140, 140)
            btn.setIconSize(QSize(110, 110))
            btn.setCursor(Qt.PointingHandCursor)
            self._add_hover_scale_animation(btn)
            self.sidebar_layout.addWidget(btn)
            
        self.sidebar_layout.addStretch()
        
        self.btn_settings = QPushButton()
        self.btn_settings.setToolTip("Settings")
        if (assets_dir / "settings.png").exists(): 
            self.btn_settings.setIcon(QIcon(str(assets_dir / "settings.png")))
        else: 
            self.btn_settings.setText("S")
        self.btn_settings.setFixedSize(140, 140)
        self.btn_settings.setIconSize(QSize(110, 110))
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self._open_settings)
        self._add_hover_scale_animation(self.btn_settings)
        self.sidebar_layout.addWidget(self.btn_settings)

        self.main_layout.addWidget(self.sidebar)

        # RIGHT MAIN AREA
        self.content_area = QFrame()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        # ---- FILE EXPLORER + CODE VIEWER (top area, split) ----
        self.file_explorer_label = QLabel(f"  \U0001f4c1 {self.project_folder.name}")
        self.file_explorer_label.setFont(QFont(self.font_family, 11, QFont.Bold))
        self.file_explorer_label.setFixedHeight(30)
        self.file_explorer_label.setStyleSheet(f"""
            QLabel {{
                color: {self.theme.text_fg};
                background-color: {getattr(self.theme, 'dimmed', '#21252b')};
                padding-left: 10px;
                border-bottom: 1px solid {getattr(self.theme, 'prompt_bg', '#3e4451')};
            }}
        """)
        self.content_layout.addWidget(self.file_explorer_label)
        
        # Splitter: file tree (left) | code viewer (right)
        self.explorer_splitter = QSplitter(Qt.Horizontal)
        self.explorer_splitter.setHandleWidth(3)
        self.explorer_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {getattr(self.theme, 'prompt_bg', '#3e4451')};
            }}
            QSplitter::handle:hover {{
                background-color: {getattr(self.theme, 'accent', '#61afef')};
            }}
        """)
        
        self.file_model = _QFileSystemModel()
        self.file_model.setRootPath(str(self.project_folder))
        self.file_model.setNameFilters(["*"])
        self.file_model.setNameFilterDisables(False)
        
        self.file_tree = QTreeView()
        self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(str(self.project_folder)))
        self.file_tree.setAnimated(True)
        self.file_tree.setIndentation(18)
        self.file_tree.setSortingEnabled(True)
        self.file_tree.sortByColumn(0, Qt.AscendingOrder)
        self.file_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_tree.clicked.connect(self._on_file_tree_clicked)
        
        # Show only Name and Size columns
        self.file_tree.setHeaderHidden(False)
        header = self.file_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_tree.hideColumn(2)  # Type
        self.file_tree.hideColumn(3)  # Date Modified
        self.file_tree.setColumnWidth(1, 80)  # Size
        
        self.file_tree.setFont(QFont(self.font_family, self.font_size))
        self.file_tree.setStyleSheet(f"""
            QTreeView {{
                background-color: {self.theme.background};
                color: {self.theme.text_fg};
                border: none;
                padding: 5px;
                outline: none;
                selection-background-color: {getattr(self.theme, 'accent', '#61afef')};
                selection-color: #ffffff;
            }}
            QTreeView::item {{
                padding: 4px 6px;
                border-radius: 4px;
            }}
            QTreeView::item:hover {{
                background-color: {getattr(self.theme, 'prompt_bg', '#3e4451')};
            }}
            QTreeView::item:selected {{
                background-color: {getattr(self.theme, 'accent', '#61afef')};
                color: #ffffff;
            }}
            QTreeView::branch {{
                background-color: {self.theme.background};
            }}
            QHeaderView::section {{
                background-color: {getattr(self.theme, 'dimmed', '#21252b')};
                color: {self.theme.text_fg};
                border: none;
                border-bottom: 1px solid {getattr(self.theme, 'prompt_bg', '#3e4451')};
                padding: 5px 8px;
                font-weight: bold;
                font-size: 11px;
            }}
        """)
        
        self.explorer_splitter.addWidget(self.file_tree)
        
        # Code viewer (right panel)
        self.code_viewer_container = QFrame()
        self.code_viewer_layout = QVBoxLayout(self.code_viewer_container)
        self.code_viewer_layout.setContentsMargins(0, 0, 0, 0)
        self.code_viewer_layout.setSpacing(0)
        
        # File name header bar with close button
        self.code_header_bar = QFrame()
        self.code_header_bar.setFixedHeight(30)
        self.code_header_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {getattr(self.theme, 'dimmed', '#21252b')};
                border-bottom: 1px solid {getattr(self.theme, 'prompt_bg', '#3e4451')};
            }}
        """)
        code_header_layout = QHBoxLayout(self.code_header_bar)
        code_header_layout.setContentsMargins(10, 0, 10, 0)  # Отступы по краям 10px
        code_header_layout.setSpacing(0)
        
        self.code_file_label = QLabel("  Select a file to preview")
        self.code_file_label.setFont(QFont(self.font_family, 10))
        self.code_file_label.setStyleSheet(f"""
            QLabel {{
                color: #ffffff;
                background: transparent;
                font-style: italic;
                border: none;
            }}
        """)
        code_header_layout.addWidget(self.code_file_label, 0, Qt.AlignVCenter)
        code_header_layout.addStretch()
        
        self.code_close_btn = QPushButton("✕")
        self.code_close_btn.setFixedSize(24, 24)
        self.code_close_btn.setCursor(Qt.PointingHandCursor)
        self.code_close_btn.setToolTip("Close file preview")
        self.code_close_btn.clicked.connect(self._close_code_viewer)
        self.code_close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {self.theme.text_fg};
                border: none;
                border-radius: 12px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #e74c3c;
                color: #ffffff;
            }}
        """)
        # ИЗМЕНЕНИЕ: Выравниваем кнопку по верхнему краю (AlignTop) и вправо (AlignRight), чтобы она сместилась вверх
        code_header_layout.addWidget(self.code_close_btn, 0, Qt.AlignTop | Qt.AlignRight)
        
        self.code_viewer_layout.addWidget(self.code_header_bar)
        
        # Code text area
        self.code_viewer = QPlainTextEdit()
        self.code_viewer.setReadOnly(True)
        self.code_viewer.setFont(QFont(self.font_family, self.font_size))
        self.code_viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.code_viewer.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {self.theme.background};
                color: {self.theme.text_fg};
                border: none;
                padding: 10px;
                selection-background-color: {getattr(self.theme, 'accent', '#61afef')};
                selection-color: #ffffff;
            }}
        """)
        self.code_viewer_layout.addWidget(self.code_viewer)
        
        self.explorer_splitter.addWidget(self.code_viewer_container)
        
        # Set initial splitter proportions: 35% tree, 65% viewer
        self.explorer_splitter.setSizes([300, 560])
        
        self.content_layout.addWidget(self.explorer_splitter)

        # ---- AGENT OUTPUT PANEL (above input, inside main scroll area) ----
        self.agent_panel = QFrame()
        self.agent_panel.setObjectName("agentPanel")
        self.agent_panel_layout = QHBoxLayout(self.agent_panel)
        self.agent_panel_layout.setContentsMargins(15, 10, 15, 5)
        self.agent_panel_layout.setSpacing(10)
        
        # Icon container with status indicator dot (left side)
        self.icon_container = QWidget()
        self.icon_container.setFixedSize(52, 52)
        self.icon_container_layout = QVBoxLayout(self.icon_container)
        self.icon_container_layout.setContentsMargins(0, 0, 0, 0)
        self.icon_container_layout.setSpacing(0)
        
        self.ai_icon_label = QLabel(self.icon_container)
        self.ai_icon_label.setFixedSize(48, 48)
        self.ai_icon_label.move(0, 0)
        
        # Status dot (bottom-right of icon)
        self.status_dot = QLabel(self.icon_container)
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.move(40, 40)
        self.status_dot.setStyleSheet("""
            QLabel {
                background-color: #555555;
                border-radius: 6px;
                border: 2px solid #333333;
            }
        """)
        
        self._update_ai_icon()
        self.agent_panel_layout.addWidget(self.icon_container, 0, Qt.AlignTop)
        
        # Right side: vertical stack of (Agent: + thinking) label row, then output
        self.agent_right = QVBoxLayout()
        self.agent_right.setSpacing(2)
        self.agent_right.setContentsMargins(0, 0, 0, 0)
        
        # "Agent:" label + thinking label on same row
        self.agent_label_row = QHBoxLayout()
        self.agent_label_row.setSpacing(10)
        
        self.status_label = QLabel("Agent:")
        self.status_label.setFont(QFont(self.font_family, 13, QFont.Bold))
        self.status_label.setStyleSheet("color: #61afef; padding: 0px;")
        self.agent_label_row.addWidget(self.status_label)
        
        self.thinking_label = QLabel("")
        self.thinking_label.setFont(QFont(self.font_family, 11))
        self.thinking_label.setStyleSheet("color: #abb2bf; font-style: italic;")
        self.agent_label_row.addWidget(self.thinking_label)
        self.agent_label_row.addStretch()
        
        self.agent_right.addLayout(self.agent_label_row)
        
        # Agent text output — sits directly under "Agent:", no gap
        self.agent_output = QTextBrowser()
        self.agent_output.setObjectName("agentOutput")
        self.agent_output.setFont(QFont(self.font_family, 11))
        self.agent_output.setReadOnly(True)
        self.agent_output.setStyleSheet("""
            QTextBrowser {
                color: #e6edf3;
                padding: 0px;
                margin: 0px;
                background: transparent;
                border: none;
                line-height: 1.5;
            }
        """)
        self.agent_output.setMinimumHeight(0)
        self.agent_output.setMaximumHeight(350)
        self.agent_output.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.agent_output.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.agent_output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.agent_right.addWidget(self.agent_output)
        
        self.agent_panel_layout.addLayout(self.agent_right, 1)
        
        # Add agent panel directly to content area (above bottom bar)
        self.content_layout.addWidget(self.agent_panel)
        
        # ---- BOTTOM BAR (input only) ----
        self.bottom_bar = QFrame()
        self.bottom_layout = QVBoxLayout(self.bottom_bar)
        self.bottom_layout.setContentsMargins(15, 5, 15, 10)
        self.bottom_layout.setSpacing(0)
        
        # Input container with buttons at top-right and model selector at bottom-right
        self.input_container = QFrame()
        self.input_container.setObjectName("inputContainer")
        self.input_container_layout = QVBoxLayout(self.input_container)
        self.input_container_layout.setContentsMargins(6, 6, 6, 6)
        self.input_container_layout.setSpacing(5)
        
        # Top row: buttons in RIGHT corner
        self.input_top_row = QHBoxLayout()
        self.input_top_row.addStretch()
        
        # Stop button
        self.stop_button = QPushButton("⏹")
        self.stop_button.setFixedSize(45, 45)
        self.stop_button.setToolTip("Stop Generation")
        self.stop_button.clicked.connect(self._stop_generation)
        self.stop_button.hide()
        self.stop_button.enterEvent = lambda e: self._animate_stop_button_enter()
        self.stop_button.leaveEvent = lambda e: self._animate_stop_button_leave()
        self.input_top_row.addWidget(self.stop_button)
        
        # Send button
        self.send_button = QPushButton("↑")
        self.send_button.setFixedSize(45, 45)
        self.send_button.setToolTip("Send Message (Enter)")
        self.send_button.clicked.connect(self._on_enter)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self._add_button_pulse_animation(self.send_button)
        self.input_top_row.addWidget(self.send_button)
        
        self.input_container_layout.addLayout(self.input_top_row)
        
        # Text field
        self.input_field = QTextEdit()
        self.input_field.setFont(QFont(self.font_family, self.font_size))
        self.input_field.setPlaceholderText("Type your message... (Shift+Enter for new line)")
        self.input_field.setMaximumHeight(70)
        self.input_field.setMinimumHeight(45)
        self.input_field.setLineWrapMode(QTextEdit.WidgetWidth)
        self.input_field.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.input_field.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_field.installEventFilter(self)
        self.input_field.setStyleSheet("""
            QTextEdit {
                padding: 8px 12px;
                font-size: 13px;
                line-height: 1.4;
            }
        """)
        
        self.input_container_layout.addWidget(self.input_field)
        
        # Bottom row: API Status on left, Model selector on right
        self.input_bottom_row = QHBoxLayout()
        
        self.api_status_label = QLabel("⚪ Idle")
        self.api_status_label.setFont(QFont(self.font_family, 10, QFont.Bold))
        self.api_status_label.setStyleSheet("color: #888888; padding: 5px;")
        self.input_bottom_row.addWidget(self.api_status_label)
        
        self.input_bottom_row.addStretch()
        
        # Model selector in BOTTOM RIGHT corner
        self.model_selector_btn = QPushButton()
        self.model_selector_btn.setCursor(Qt.PointingHandCursor)
        self.model_selector_btn.setFixedHeight(38)
        self.model_selector_btn.setMinimumWidth(140)
        self._add_button_hover_glow(self.model_selector_btn)
        
        self.model_menu = QMenu(self)
        self.model_menu.setStyleSheet("""
            QMenu { 
                background-color: #282c34; 
                color: #abb2bf; 
                border: 2px solid #3e4451;
                border-radius: 8px;
                padding: 8px;
            }
            QMenu::item { 
                padding: 10px 35px;
                border-radius: 6px;
            }
            QMenu::item:selected { 
                background-color: #3e4451; 
                color: #ffffff;
            }
        """)
        
        # Add fade animation to menu
        self.model_menu.aboutToShow.connect(self._animate_menu_show)
        
        # Group ALL models from AVAILABLE_MODELS by provider
        providers = {}
        for alias in AVAILABLE_MODELS.keys():
            parts = alias.split('-')
            provider = parts[0].title()
            if provider == "Gpt": provider = "OpenAI"
            if provider not in providers:
                providers[provider] = []
            providers[provider].append(alias)
            
        for provider, aliases in providers.items():
            prefix = provider.lower()
            if prefix == "openai": prefix = "chatgpt"
            
            icon_path = assets_dir / f"{prefix}.png"
            if prefix == "chatgpt": icon_path = assets_dir / "chatgpt.png"
            
            provider_menu = self.model_menu.addMenu(provider)
            if icon_path.exists():
                icon = QIcon(str(icon_path))
                provider_menu.setIcon(icon)
                
            for alias in sorted(aliases):
                display_name = alias.replace('-', ' ').title()
                display_name = display_name.replace('Gpt', 'GPT')
                action = provider_menu.addAction(display_name)
                if icon_path.exists():
                    action.setIcon(QIcon(str(icon_path)))
                action.triggered.connect(lambda checked, a=alias: self._select_model(a))

        self.model_selector_btn.setMenu(self.model_menu)
        self.input_bottom_row.addWidget(self.model_selector_btn)
        
        self.input_container_layout.addLayout(self.input_bottom_row)
        
        self.bottom_layout.addWidget(self.input_container)
        self.content_layout.addWidget(self.bottom_bar)
        self.main_layout.addWidget(self.content_area)
        
        self._update_model_selection_ui()

    def _set_api_status(self, status: str):
        """Устанавливает визуальный статус API"""
        if status == "idle":
            self.api_status_label.setText("⚪ Idle")
            self.api_status_label.setStyleSheet("color: #888888; padding: 5px;")
        elif status == "thinking":
            self.api_status_label.setText("🟡 Thinking...")
            self.api_status_label.setStyleSheet("color: #e5c07b; padding: 5px;")
        elif status == "online":
            self.api_status_label.setText("🟢 API Online")
            self.api_status_label.setStyleSheet("color: #2ecc71; padding: 5px;")
        elif status == "error":
            self.api_status_label.setText("🔴 API Error")
            self.api_status_label.setStyleSheet("color: #e74c3c; padding: 5px;")

    def _apply_theme(self):
        bg = self.theme.background
        fg = self.theme.text_fg
        accent = getattr(self.theme, "accent", "#61afef")
        prompt_bg = getattr(self.theme, "prompt_bg", "#3e4451")
        sidebar_bg = getattr(self.theme, "dimmed", "#21252b")
        
        # UNIQUE styles for each theme
        theme_name = self.theme.name
        
        # Border styles vary by theme
        border_styles = {
            "dark": "border-radius: 10px; border: 3px solid",
            "hacker": "border-radius: 0px; border: 2px solid; border-style: dashed",
            "neon": "border-radius: 15px; border: 4px solid; box-shadow: 0 0 20px",
            "ocean": "border-radius: 12px; border: 3px solid; border-style: double",
            "sunset": "border-radius: 8px; border: 3px solid; background: linear-gradient(135deg, #2a0a0a, #3d1414)",
            "dracula": "border-radius: 6px; border: 2px solid",
            "cyberpunk": "border-radius: 0px; border: 3px solid; border-style: solid; box-shadow: 0 0 25px",
            "monokai": "border-radius: 8px; border: 2px solid",
            "nord": "border-radius: 10px; border: 2px solid",
            "gruvbox": "border-radius: 5px; border: 3px solid",
            "tokyonight": "border-radius: 12px; border: 2px solid; box-shadow: 0 0 15px",
            "catppuccin": "border-radius: 14px; border: 3px solid",
            "onedark": "border-radius: 8px; border: 2px solid",
            "solarized": "border-radius: 10px; border: 3px solid; border-style: groove",
            "material": "border-radius: 4px; border: 1px solid",
            "ayu": "border-radius: 6px; border: 2px solid",
            "github": "border-radius: 8px; border: 2px solid",
            "vscode": "border-radius: 5px; border: 1px solid",
            "atom": "border-radius: 10px; border: 2px solid",
            "twilight": "border-radius: 15px; border: 3px solid; box-shadow: 0 0 30px",
        }
        
        # Button styles vary by theme
        button_styles = {
            "dark": "padding: 10px 15px; font-weight: bold;",
            "hacker": "padding: 8px 12px; font-weight: normal; font-family: 'Courier New'; text-transform: uppercase;",
            "neon": "padding: 12px 18px; font-weight: bold; text-shadow: 0 0 10px;",
            "ocean": "padding: 10px 15px; font-weight: 600;",
            "sunset": "padding: 10px 15px; font-weight: bold; font-style: italic;",
            "dracula": "padding: 10px 15px; font-weight: 600;",
            "cyberpunk": "padding: 8px 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 2px;",
            "monokai": "padding: 10px 15px; font-weight: normal;",
            "nord": "padding: 10px 15px; font-weight: 500;",
            "gruvbox": "padding: 12px 16px; font-weight: bold;",
            "tokyonight": "padding: 10px 15px; font-weight: 600;",
            "catppuccin": "padding: 11px 16px; font-weight: 600;",
            "onedark": "padding: 10px 15px; font-weight: normal;",
            "solarized": "padding: 10px 15px; font-weight: 500;",
            "material": "padding: 8px 16px; font-weight: 500; text-transform: uppercase; letter-spacing: 1px;",
            "ayu": "padding: 10px 15px; font-weight: normal;",
            "github": "padding: 10px 15px; font-weight: 600;",
            "vscode": "padding: 10px 15px; font-weight: 500;",
            "atom": "padding: 10px 15px; font-weight: normal;",
            "twilight": "padding: 12px 18px; font-weight: bold; text-shadow: 0 0 8px;",
        }
        
        border_style = border_styles.get(theme_name, "border-radius: 10px; border: 3px solid")
        button_style = button_styles.get(theme_name, "padding: 10px 15px; font-weight: bold;")

        self.setStyleSheet(f"""
            QMainWindow {{ 
                background-color: {bg}; 
            }}
            QFrame {{ 
                background-color: {bg}; 
                border: none; 
            }}
            QTextEdit {{
                background-color: {bg};
                color: {fg};
                border: none;
                padding: 15px;
                font-size: 13px;
                line-height: 1.5;
            }}
            /* Sidebar styles */
            QFrame#sidebar {{
                background-color: {sidebar_bg};
                border-right: 3px solid {prompt_bg};
            }}
            /* Agent output inline - QTextBrowser that can expand */
            QTextBrowser#agentOutput {{
                background-color: transparent;
                color: {fg};
                border: none;
                padding: 5px 10px;
                font-size: 13px;
                line-height: 1.6;
            }}
            /* Input container with border */
            QFrame#inputContainer {{
                background-color: {prompt_bg};
                {border_style} {accent};
                padding: 8px;
                margin: 5px;
            }}
            QFrame#inputContainer QTextEdit {{
                background-color: {prompt_bg};
                color: {fg};
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                line-height: 1.4;
            }}
            QFrame#inputContainer QTextEdit::placeholder {{
                color: {accent};
                opacity: 0.5;
                font-style: italic;
            }}
            QScrollBar:vertical {{
                background-color: {prompt_bg};
                width: 14px;
                border-radius: 7px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {accent};
                border-radius: 7px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {fg};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            QPushButton {{
                background-color: {prompt_bg};
                color: {fg};
                border: 3px solid {accent};
                {button_style}
                {border_style.split(';')[0]};
                min-height: 35px;
            }}
            QPushButton:hover {{
                background-color: {accent};
                color: {bg};
                border: 3px solid {accent};
                transform: scale(1.02);
            }}
            QPushButton::menu-indicator {{ 
                image: none; 
            }}
            QLabel {{
                color: {fg};
                font-weight: bold;
            }}
        """)
        self.sidebar.setObjectName("sidebar")
        self.agent_output.setObjectName("agentOutput")
        self.input_container.setObjectName("inputContainer")
        
        # Update themed buttons
        self._update_themed_buttons()
    
    def _update_themed_buttons(self):
        """Update send/stop button colors based on theme"""
        accent = getattr(self.theme, "accent", "#61afef")
        bg = self.theme.background
        fg = self.theme.text_fg
        prompt_bg = getattr(self.theme, "prompt_bg", "#3e4451")
        theme_name = self.theme.name
        
        # UNIQUE send button styles per theme
        send_styles = {
            "dark": """
                QPushButton {
                    background-color: #27ae60; color: white;
                    border: none; border-radius: 20px;
                    font-size: 22px; font-weight: bold;
                }
                QPushButton:hover { background-color: #2ecc71; }
            """,
            "hacker": """
                QPushButton {
                    background-color: #00ff00; color: #000000;
                    border: 2px solid #00ff00; border-radius: 0px;
                    font-size: 20px; font-weight: bold; font-family: 'Courier New';
                }
                QPushButton:hover { background-color: #00cc00; box-shadow: 0 0 15px #00ff00; }
            """,
            "neon": """
                QPushButton {
                    background-color: #ff00ff; color: white;
                    border: 3px solid #ff00ff; border-radius: 20px;
                    font-size: 22px; font-weight: bold; box-shadow: 0 0 20px #ff00ff;
                }
                QPushButton:hover { background-color: #cc00cc; box-shadow: 0 0 30px #ff00ff; }
            """,
            "ocean": """
                QPushButton {
                    background-color: #0077be; color: white;
                    border: 2px solid #0099ff; border-radius: 20px;
                    font-size: 22px; font-weight: bold;
                }
                QPushButton:hover { background-color: #0099ff; }
            """,
            "sunset": """
                QPushButton {
                    background-color: #ff6b35; color: white;
                    border: none; border-radius: 20px;
                    font-size: 22px; font-weight: bold; font-style: italic;
                }
                QPushButton:hover { background-color: #ff8c61; }
            """,
            "cyberpunk": """
                QPushButton {
                    background-color: #00ffff; color: #000000;
                    border: 3px solid #00ffff; border-radius: 0px;
                    font-size: 20px; font-weight: bold; text-transform: uppercase;
                    box-shadow: 0 0 25px #00ffff;
                }
                QPushButton:hover { background-color: #00cccc; box-shadow: 0 0 35px #00ffff; }
            """,
            "material": """
                QPushButton {
                    background-color: #2196f3; color: white;
                    border: none; border-radius: 4px;
                    font-size: 22px; font-weight: 500;
                }
                QPushButton:hover { background-color: #1976d2; }
            """,
            "twilight": """
                QPushButton {
                    background-color: #9d4edd; color: white;
                    border: 3px solid #c77dff; border-radius: 25px;
                    font-size: 22px; font-weight: bold; box-shadow: 0 0 20px #9d4edd;
                }
                QPushButton:hover { background-color: #c77dff; box-shadow: 0 0 35px #c77dff; }
            """,
        }
        
        # Stop button styles per theme
        stop_styles = {
            "dark": """
                QPushButton {
                    background-color: #e74c3c; color: white;
                    border: none; border-radius: 20px;
                    font-size: 20px; font-weight: bold;
                }
                QPushButton:hover { background-color: #c0392b; border: 2px solid #ffffff; }
            """,
            "hacker": """
                QPushButton {
                    background-color: #ff0000; color: #000000;
                    border: 2px solid #ff0000; border-radius: 0px;
                    font-size: 18px; font-weight: bold; font-family: 'Courier New';
                }
                QPushButton:hover { background-color: #cc0000; box-shadow: 0 0 15px #ff0000; }
            """,
            "neon": """
                QPushButton {
                    background-color: #ff0066; color: white;
                    border: 3px solid #ff0066; border-radius: 20px;
                    font-size: 20px; font-weight: bold; box-shadow: 0 0 20px #ff0066;
                }
                QPushButton:hover { background-color: #cc0044; box-shadow: 0 0 30px #ff0066; }
            """,
            "cyberpunk": """
                QPushButton {
                    background-color: #ff0066; color: white;
                    border: 3px solid #ff0066; border-radius: 0px;
                    font-size: 18px; font-weight: bold;
                    box-shadow: 0 0 25px #ff0066;
                }
                QPushButton:hover { background-color: #cc0044; box-shadow: 0 0 35px #ff0066; }
            """,
            "twilight": """
                QPushButton {
                    background-color: #ff006e; color: white;
                    border: 3px solid #ff006e; border-radius: 25px;
                    font-size: 20px; font-weight: bold; box-shadow: 0 0 20px #ff006e;
                }
                QPushButton:hover { background-color: #d90059; box-shadow: 0 0 35px #ff006e; }
            """,
        }
        
        # Default styles
        default_send = f"""
            QPushButton {{
                background-color: #27ae60; color: white;
                border: none; border-radius: 20px;
                font-size: 22px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #2ecc71; }}
        """
        
        default_stop = f"""
            QPushButton {{
                background-color: #e74c3c; color: white;
                border: none; border-radius: 20px;
                font-size: 20px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #c0392b; border: 2px solid #ffffff; }}
        """
        
        self.send_button.setStyleSheet(send_styles.get(theme_name, default_send))
        self.stop_button.setStyleSheet(stop_styles.get(theme_name, default_stop))
        
        # Model selector with theme colors
        self.model_selector_btn.setStyleSheet(f"""
            QPushButton {{
                padding: 8px 12px; 
                border-radius: 6px;
                background-color: {prompt_bg};
                color: {fg};
                border: 2px solid {accent};
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {accent};
                color: {bg};
            }}
        """)
    
    def _add_scale_animation(self, widget):
        """Add scale animation effect on hover"""
        original_size = widget.size()
        
        def on_enter(event):
            pass  # Keep size stable for now
        
        def on_leave(event):
            pass
        
        widget.enterEvent = on_enter
        widget.leaveEvent = on_leave
    
    def _add_hover_scale_animation(self, button):
        """Add smooth scale + glow effect on hover for big sidebar buttons"""
        original_style = button.styleSheet()
        
        def on_enter(event):
            # Scale up slightly with glow effect
            button.setStyleSheet(original_style + """
                QPushButton {
                    background-color: rgba(97, 175, 239, 0.15);
                    border: 3px solid #61afef;
                    transform: scale(1.05);
                }
            """)
            # Create opacity animation
            effect = QGraphicsOpacityEffect(button)
            button.setGraphicsEffect(effect)
            
            animation = QPropertyAnimation(effect, b"opacity")
            animation.setDuration(200)
            animation.setStartValue(0.7)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.InOutQuad)
            animation.start()
            button._hover_animation = animation
        
        def on_leave(event):
            button.setStyleSheet(original_style)
            button.setGraphicsEffect(None)
        
        button.enterEvent = on_enter
        button.leaveEvent = on_leave
    
    def _animate_stop_button_enter(self):
        """Animate stop button on hover - scale up"""
        self.stop_button.setFixedSize(50, 50)
        
    def _animate_stop_button_leave(self):
        """Animate stop button on leave - scale down"""
        self.stop_button.setFixedSize(45, 45)
    
    def _apply_theme_with_animation(self, theme_name: str):
        """Apply new theme with smooth fade transition"""
        # Fade out
        fade_out = QPropertyAnimation(self, b"windowOpacity")
        fade_out.setDuration(200)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.7)
        fade_out.setEasingCurve(QEasingCurve.InOutQuad)
        
        def on_fade_out_finished():
            # Change theme
            self._execute_command(f"/theme {theme_name}")
            
            # Fade back in
            fade_in = QPropertyAnimation(self, b"windowOpacity")
            fade_in.setDuration(200)
            fade_in.setStartValue(0.7)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.InOutQuad)
            fade_in.start()
            self._theme_fade_in = fade_in
        
        fade_out.finished.connect(on_fade_out_finished)
        fade_out.start()
        self._theme_fade_out = fade_out
    
    def _add_button_pulse_animation(self, button):
        """Add smooth pulse animation on hover for send button"""
        def on_enter(event):
            # Create glow effect
            effect = QGraphicsOpacityEffect(button)
            button.setGraphicsEffect(effect)
            
            # Pulse animation
            animation = QPropertyAnimation(effect, b"opacity")
            animation.setDuration(300)
            animation.setStartValue(0.8)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.InOutQuad)
            animation.setLoopCount(-1)  # Loop forever
            animation.start()
            button._pulse_animation = animation
        
        def on_leave(event):
            if hasattr(button, '_pulse_animation'):
                button._pulse_animation.stop()
            button.setGraphicsEffect(None)
        
        button.enterEvent = on_enter
        button.leaveEvent = on_leave
    
    def _add_button_hover_glow(self, button):
        """Add glow effect on hover for model selector"""
        original_style = button.styleSheet()
        
        def on_enter(event):
            # Add glow border
            current_style = button.styleSheet()
            button.setStyleSheet(current_style + """
                QPushButton {
                    border: 3px solid #61afef;
                    box-shadow: 0 0 15px rgba(97, 175, 239, 0.5);
                }
            """)
        
        def on_leave(event):
            button.setStyleSheet(original_style)
        
        button.enterEvent = on_enter
        button.leaveEvent = on_leave
    
    def _animate_button_swap(self, hide_btn, show_btn):
        """Smoothly swap two buttons with fade animation"""
        # Fade out the button to hide
        hide_effect = QGraphicsOpacityEffect(hide_btn)
        hide_btn.setGraphicsEffect(hide_effect)
        
        fade_out = QPropertyAnimation(hide_effect, b"opacity")
        fade_out.setDuration(150)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.InOutQuad)
        
        def on_fade_out_finished():
            hide_btn.hide()
            hide_btn.setGraphicsEffect(None)
            
            # Fade in the button to show
            show_btn.show()
            show_effect = QGraphicsOpacityEffect(show_btn)
            show_btn.setGraphicsEffect(show_effect)
            
            fade_in = QPropertyAnimation(show_effect, b"opacity")
            fade_in.setDuration(150)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.InOutQuad)
            
            def on_fade_in_finished():
                show_btn.setGraphicsEffect(None)
            
            fade_in.finished.connect(on_fade_in_finished)
            fade_in.start()
            self._button_fade_in = fade_in
        
        fade_out.finished.connect(on_fade_out_finished)
        fade_out.start()
        self._button_fade_out = fade_out
    
    def _animate_menu_show(self):
        """Animate menu appearance with fade and scale"""
        effect = QGraphicsOpacityEffect(self.model_menu)
        self.model_menu.setGraphicsEffect(effect)
        
        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(200)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutQuad)
        animation.start()
        self._menu_animation = animation
    
    def _update_ai_icon(self):
        """Update AI icon based on current model - SAME SIZE for all"""
        assets_dir = Path(__file__).parent / "assets"
        prefix = self.model_alias.split('-')[0].lower()
        if prefix == "gpt": prefix = "chatgpt"
        icon_path = assets_dir / f"{prefix}.png"
        
        if icon_path.exists():
            # FIXED SIZE 48x48 for ALL models
            pixmap = QPixmap(str(icon_path)).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.ai_icon_label.setPixmap(pixmap)
            self.ai_icon_label.setFixedSize(48, 48)
            # NO BORDER - clean icon
            self.ai_icon_label.setStyleSheet("")
            
        # Start animation
        self._start_ai_icon_animation()
    
    def _start_ai_icon_animation(self):
        """Server diode animation - status indicator only"""
        if not hasattr(self, 'icon_animation_timer'):
            self.icon_animation_timer = QTimer(self)
            self.icon_animation_timer.timeout.connect(self._animate_ai_icon)
            self.icon_animation_phase = 0
        
        if self.is_generating:
            # Fast blinks like server activity LED - 150ms
            self.icon_animation_timer.start(150)
        else:
            self.icon_animation_timer.stop()
            # Reset status dot to idle (gray)
            self.status_dot.setStyleSheet("""
                QLabel {
                    background-color: #555555;
                    border-radius: 6px;
                    border: 2px solid #333333;
                }
            """)
    
    def _animate_ai_icon(self):
        """Server diode animation - static icon with blinking status dot"""
        import random
        
        self.icon_animation_phase += 1
        
        # Status dot blinks like HDD activity LED
        # Random blinks to simulate server activity
        if self.icon_animation_phase % 3 == 0:
            # Active state - bright color
            accent = getattr(self.theme, "accent", "#61afef")
            self.status_dot.setStyleSheet(f"""
                QLabel {{
                    background-color: {accent};
                    border-radius: 6px;
                    border: 2px solid #ffffff;
                    box-shadow: 0 0 8px {accent};
                }}
            """)
        elif self.icon_animation_phase % 3 == 1:
            # Dimmed state
            self.status_dot.setStyleSheet("""
                QLabel {
                    background-color: #777777;
                    border-radius: 6px;
                    border: 2px solid #555555;
                }
            """)
        else:
            # Off state (like HDD not reading)
            self.status_dot.setStyleSheet("""
                QLabel {
                    background-color: #444444;
                    border-radius: 6px;
                    border: 2px solid #333333;
                }
            """)
        
        # Icon stays STATIC - no scaling or movement
    
    def eventFilter(self, obj, event):
        """Handle Shift+Enter for multiline, Enter for send, and Up/Down for history"""
        if obj == self.input_field and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                if event.modifiers() & Qt.ShiftModifier:
                    # Shift+Enter: add newline
                    return False
                else:
                    # Enter: send message
                    self._on_enter()
                    return True
            
            # НАВИГАЦИЯ ПО ИСТОРИИ ВВОДА (СТРЕЛКИ ВВЕРХ/ВНИЗ)
            elif event.key() == Qt.Key_Up:
                if self.prompt_history:
                    if self.history_index < len(self.prompt_history) - 1:
                        self.history_index += 1
                        self.input_field.setPlainText(self.prompt_history[self.history_index])
                        self.input_field.moveCursor(QTextCursor.End)
                        return True
            elif event.key() == Qt.Key_Down:
                if self.history_index > 0:
                    self.history_index -= 1
                    self.input_field.setPlainText(self.prompt_history[self.history_index])
                    self.input_field.moveCursor(QTextCursor.End)
                    return True
                elif self.history_index == 0:
                    self.history_index = -1
                    self.input_field.clear()
                    return True
        return super().eventFilter(obj, event)

    def _update_model_selection_ui(self):
        assets_dir = Path(__file__).parent / "assets"
        prefix = self.model_alias.split('-')[0].lower()
        if prefix == "gpt": prefix = "chatgpt"
        icon_path = assets_dir / f"{prefix}.png"
        
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            self.model_selector_btn.setIcon(icon)
            # FIXED SIZE 32x32 for ALL models in selector
            self.model_selector_btn.setIconSize(QSize(32, 32))
        
        display_name = self.model_alias.replace('-', ' ').title()
        display_name = display_name.replace('Gpt', 'GPT')
        self.model_selector_btn.setText(f"  {display_name}  ")
        self.model_selector_btn.setFont(QFont(self.font_family, 11, QFont.Bold))
        self._update_ai_icon()
        self._update_themed_buttons()

    def _select_model(self, alias: str):
        self.model_alias = alias
        # For simplicity in GUI test, map unknown aliases to DEFAULT_MODEL or let client handle it
        model_id = AVAILABLE_MODELS.get(alias, alias)
        self.client.model = model_id
        self.app_instance.client.model = self.client.model
        self._update_model_selection_ui()
        
        # Save to settings
        settings = _load_global_settings()
        settings["model"] = alias
        _save_global_settings(settings)
        
        if getattr(self.app_instance.client, 'debug_mode', False):
            print(f"\n[System] Switched model to: {alias}")

    def _append_text(self, text: str):
        # Перехватываем ошибки API, даже если клиент не выбросил исключение
        if self.is_generating:
            lower_text = text.lower()
            error_keywords = ["error", "failed", "503", "502", "500", "overloaded", "offline", "unavailable", "timeout", "unable to"]
            if any(kw in lower_text for kw in error_keywords):
                self._set_api_status("error")
        
        # Skip unwanted outputs - comprehensive filtering
        skip_patterns = [
            "Hi! I'm Claude",
            "made by Anthropic",
            "Looks like a stray keypress",
            "Welcome to Unlimited Code",
            "[System] Settings updated",
            "Connecting to API",
            "Status: 200",
            "Streaming response",
            "(attempt",
            "attempt 1/3",
            "attempt 2/3", 
            "attempt 3/3",
            "Привет!",
            "👋",
        ]
        
        for pattern in skip_patterns:
            if pattern in text:
                return
        
        # Skip lines that only contain theme/project info
        stripped = text.strip()
        if stripped.startswith("Theme:") or stripped.startswith("Project:"):
            return
        if stripped.startswith("Чем могу помочь с твоим проектом"):
            return
        if stripped == "=" * 60 or stripped == "=" * len(stripped):
            return
        
        # Skip ONLY specific error messages (unless debug mode)
        if not getattr(self.client, 'debug_mode', False):
            if "[Error]:" in text:
                return
            if "peer closed connection" in text:
                return
            if "incomplete chunked read" in text:
                return
            
        # During generation: write ONLY to agent_output, not file tree
        if self.is_generating:
            current = self.agent_output.toPlainText()
            combined = current + text
            if len(combined) > 50000:
                combined = combined[-50000:]
            self.agent_output.setPlainText(combined)
            self.agent_output.moveCursor(QTextCursor.End)
            return
            
        # When not generating: show system messages in agent_output too
        current = self.agent_output.toPlainText()
        self.agent_output.setPlainText(current + text)
        self.agent_output.moveCursor(QTextCursor.End)
    
    def _open_history(self):
        dialog = ChatHistoryDialog(self)
        dialog.exec_()
    
    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", str(self.project_folder))
        if folder:
            self.project_folder = Path(folder)
            self.client.project_folder = self.project_folder
            self.app_instance.project_folder = self.project_folder
            self.client.tools.project_folder = self.project_folder
            
            # Update file tree to show new folder
            self.file_model.setRootPath(str(self.project_folder))
            self.file_tree.setRootIndex(self.file_model.index(str(self.project_folder)))
            self.file_explorer_label.setText(f"  \U0001f4c1 {self.project_folder.name}")
            
            # Clear code viewer
            self.code_viewer.setPlainText("")
            self.code_file_label.setText("  Select a file to preview")
            
            # Save to settings
            settings = _load_global_settings()
            settings["project"] = str(self.project_folder)
            _save_global_settings(settings)
    
    def _on_file_tree_clicked(self, index: QModelIndex):
        """When a file is clicked in the tree, show its contents in the code viewer."""
        file_path = self.file_model.filePath(index)
        if not file_path:
            return
        
        path = Path(file_path)
        
        # Skip directories
        if path.is_dir():
            return
        
        # Check file size — skip if too large (> 2MB)
        try:
            size = path.stat().st_size
            if size > 2 * 1024 * 1024:
                self.code_file_label.setText(f"  \u26a0 {path.name} — too large ({size // 1024} KB)")
                self.code_viewer.setPlainText("File too large to preview.")
                return
        except OSError:
            return
        
        # Binary file detection
        binary_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp',
            '.mp3', '.wav', '.ogg', '.mp4', '.avi', '.mkv', '.mov',
            '.zip', '.tar', '.gz', '.7z', '.rar',
            '.exe', '.dll', '.so', '.dylib', '.pyc', '.pyd',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx',
            '.db', '.sqlite', '.sqlite3',
        }
        if path.suffix.lower() in binary_extensions:
            self.code_file_label.setText(f"  \U0001f4ce {path.name} — binary file")
            self.code_viewer.setPlainText(f"[Binary file: {path.suffix}, {size:,} bytes]")
            return
        
        # Read text file
        try:
            encodings = ['utf-8', 'utf-8-sig', 'cp1251', 'latin-1']
            content = None
            for enc in encodings:
                try:
                    content = path.read_text(encoding=enc)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            
            if content is None:
                self.code_file_label.setText(f"  \u26a0 {path.name} — encoding error")
                self.code_viewer.setPlainText("Cannot decode file.")
                return
            
            # Применяем автодекодер бинарного кода к содержимому файла
            content = clean_binary_text(content)
            
            # Update header with file name and line count
            line_count = content.count('\n') + 1
            self.code_file_label.setText(f"  \U0001f4c4 {path.name}  \u2014  {line_count} lines  \u2014  {size:,} bytes")
            self.code_file_label.setStyleSheet(f"""
                QLabel {{
                    color: {getattr(self.theme, 'accent', '#61afef')};
                    background-color: {getattr(self.theme, 'dimmed', '#21252b')};
                    padding-left: 10px;
                    border-bottom: 1px solid {getattr(self.theme, 'prompt_bg', '#3e4451')};
                    font-style: normal;
                    font-weight: bold;
                }}
            """)
            
            # Fade-in animation for the code viewer
            effect = QGraphicsOpacityEffect(self.code_viewer)
            self.code_viewer.setGraphicsEffect(effect)
            
            self.code_viewer.setPlainText(content)
            self.code_viewer.moveCursor(QTextCursor.Start)
            
            anim = QPropertyAnimation(effect, b"opacity")
            anim.setDuration(250)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            
            def on_done():
                self.code_viewer.setGraphicsEffect(None)
            
            anim.finished.connect(on_done)
            anim.start()
            self._code_fade_anim = anim
            
        except Exception as e:
            self.code_file_label.setText(f"  \u26a0 {path.name} — error")
            self.code_viewer.setPlainText(f"Error reading file: {e}")

    def _close_code_viewer(self):
        """Очищает просмотрщик кода, сбрасывает заголовок и снимает выделение в дереве файлов."""
        self.code_viewer.setPlainText("")
        self.code_file_label.setText("  Select a file to preview")
        self.code_file_label.setStyleSheet(f"""
            QLabel {{
                color: #ffffff;
                background: transparent;
                font-style: italic;
                border: none;
            }}
        """)
        # Снимаем выделение с файла в дереве
        if hasattr(self, 'file_tree'):
            self.file_tree.clearSelection()
        
    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            new_theme = dialog.theme_combo.currentText()
            new_font = dialog.font_combo.currentText()
            new_size = int(dialog.font_size_combo.currentText())
            new_instruction = dialog.instruction_edit.toPlainText().strip()
            new_reasoning = dialog.reasoning_combo.currentText()
            
            settings_changed = False
            
            if new_theme != self.theme.name:
                self._apply_theme_with_animation(new_theme)
                settings_changed = True
            
            if new_font != self.font_family or new_size != self.font_size:
                self.font_family = new_font
                self.font_size = new_size
                self.file_tree.setFont(QFont(new_font, new_size))
                self.code_viewer.setFont(QFont(new_font, new_size))
                self.input_field.setFont(QFont(new_font, new_size))
                self.agent_output.setFont(QFont(new_font, new_size))
                settings_changed = True
            
            # Update system instruction
            self.system_instruction = new_instruction
            
            # Пытаемся применить инструкцию к клиенту всеми возможными способами
            if hasattr(self.client, 'system_instruction'):
                self.client.system_instruction = new_instruction
            if hasattr(self.client, 'system_prompt'):
                self.client.system_prompt = new_instruction
            if hasattr(self.app_instance, 'client'):
                self.app_instance.client.system_instruction = new_instruction
                if hasattr(self.app_instance.client, 'system_prompt'):
                    self.app_instance.client.system_prompt = new_instruction
            
            if new_reasoning != self.reasoning_effort:
                self.reasoning_effort = new_reasoning
                effort_val = new_reasoning.lower() if new_reasoning != "Default" else None
                if hasattr(self.client, 'reasoning_effort'):
                    self.client.reasoning_effort = effort_val
                if hasattr(self.client, 'thinking'):
                    self.client.thinking = effort_val
                if hasattr(self.client, 'effort'):
                    self.client.effort = effort_val
                settings_changed = True
                
            settings_changed = True
            
            if settings_changed:
                settings = _load_global_settings()
                settings["font_family"] = self.font_family
                settings["font_size"] = self.font_size
                settings["system_instruction"] = self.system_instruction
                settings["reasoning_effort"] = self.reasoning_effort
                _save_global_settings(settings)

    def _execute_command(self, cmd_text: str):
        try:
            # Special handling for /newchat to suppress output
            if cmd_text.strip().lower() in ["/newchat", "/chats new"]:
                self.app_instance._auto_save_chat()
                self.app_instance.client.reset()
                self.app_instance.current_chat_id = None
                self.app_instance.current_chat_name = "untitled"
                self.agent_output.setPlainText("")
                return
            
            if self.app_instance._handle_command(cmd_text):
                try:
                    self.app_instance._auto_save_chat()
                except Exception:
                    pass
                if self.app_instance.theme.name != self.theme.name:
                    self.theme = self.app_instance.theme
                    self._apply_theme()
                    self._update_model_selection_ui()
                    
                    # Save theme to settings
                    settings = _load_global_settings()
                    settings["theme"] = self.theme.name
                    _save_global_settings(settings)
        except Exception as e:
            print(f"Command Error: {e}")

    def _update_thinking_label(self):
        dots = "." * ((self.thinking_index % 3) + 1)
        phrase = random.choice(self.thinking_phrases)
        self.thinking_label.setText(f"{phrase}{dots}")
        self.thinking_index += 1
    
    def _stop_generation(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)
            self._on_response_done()

    def _on_enter(self):
        text = self.input_field.toPlainText().strip()
        if not text:
            return
            
        self.input_field.clear()
        # Don't print "unlimited> text" - removed
        
        if text.startswith("/clear"):
            self.agent_output.setPlainText("")
            return
            
        if text.startswith("/"):
            self._execute_command(text)
            return

        # СОХРАНЕНИЕ ИСТОРИИ ВВОДА
        if text not in self.prompt_history:
            self.prompt_history.insert(0, text)
            self.prompt_history = self.prompt_history[:100] # Ограничиваем 100 записями
            _save_prompt_history(self.prompt_history)
        self.history_index = -1 # Сбрасываем индекс истории
        
        # Clear agent output before new generation with fade animation
        self._fade_out_agent_output()
        
        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)
        self.is_generating = True
        self._set_api_status("thinking")
        self.thinking_label.setText("Thinking.")
        self.thinking_index = 0
        self.thinking_timer.start(800)  # SLOWER - 800ms instead of 500ms
        
        # Smooth show/hide animation for stop/send buttons
        self._animate_button_swap(hide_btn=self.send_button, show_btn=self.stop_button)
        
        # Start AI icon animation
        self._start_ai_icon_animation()
        
        # Передаем системную инструкцию в воркер
        self.worker = AgentWorker(self.client, text, self.system_instruction)
        self.worker.finished.connect(self._on_response_done)
        self.worker.error_occurred.connect(self._on_worker_error)
        self.worker.start()
    
    def _fade_out_agent_output(self):
        """Fade out agent output before clearing"""
        effect = QGraphicsOpacityEffect(self.agent_output)
        self.agent_output.setGraphicsEffect(effect)
        
        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(200)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.InOutQuad)
        
        def on_finished():
            self.agent_output.setPlainText("")
            self.agent_output.setGraphicsEffect(None)
        
        animation.finished.connect(on_finished)
        animation.start()
        self._agent_fade_animation = animation

    def _on_worker_error(self, error_msg: str):
        """Show errors visibly in the agent output so the user knows what went wrong."""
        self.agent_output.setPlainText(f"[Error] {error_msg}")
        self._set_api_status("error")

    def _on_response_done(self):
        self.thinking_timer.stop()
        self.input_field.setEnabled(True)
        self.send_button.setEnabled(True)
        self.thinking_label.setText("")
        self.is_generating = False
        
        # Smooth show/hide animation for send/stop buttons
        self._animate_button_swap(hide_btn=self.stop_button, show_btn=self.send_button)
        
        self.input_field.setFocus()
        
        # Stop AI icon animation
        self._start_ai_icon_animation()
        
        # Если статус не был изменен на Error во время генерации, значит всё прошло успешно
        if "Error" not in self.api_status_label.text():
            self._set_api_status("online")
        
        # Auto-save chat after response
        try:
            self.app_instance._auto_save_chat()
        except Exception:
            pass

    def closeEvent(self, event):
        sys.stdout = self.redirector.original_stdout
        sys.stderr = self.redirector.original_stderr
        event.accept()
    
    def resizeEvent(self, event):
        """Update button position on window resize"""
        super().resizeEvent(event)
        # Move buttons to top right corner
        if hasattr(self, 'top_buttons_container'):
            window_width = self.content_area.width()
            self.top_buttons_container.move(window_width - 110, 10)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CustomConsoleGUI()
    window.show()
    sys.exit(app.exec_())