#!/usr/bin/env python3
"""Unlimited Code — console AI coding agent."""

import os
import sys
import json
import re
import argparse
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.tree import Tree
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style


BASE_URL = os.environ.get("UNLIMITED_BASE_URL", "https://unlimited.surf").rstrip("/")
API_KEY = os.environ.get("UNLIMITED_API_KEY", "YOUR_API_KEY_HERE").strip()
CHAT_ENDPOINT = f"{BASE_URL}/api/chat"

# Bundled logo (PNG). Used by /theme header and by the TUI version.
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"


AVAILABLE_MODELS = {
    "claude-opus-4.7": "gateway-claude-opus-4-7",
    "claude-opus-4.8": "gateway-claude-opus-4-8",
    "claude-sonnet-4.6": "gateway-claude-sonnet-4-6",
    "claude-opus-4.6": "gateway-claude-opus-4-6",
    "gpt-5.5": "gateway-gpt-5-5",
    "gpt-5.4": "gateway-gpt-5-4",
    "gpt-5.3": "gateway-gpt-5-3",
    "gpt-5.2": "gateway-gpt-5-2",
    "gpt-5.1": "gateway-gpt-5-1",
    "gpt-5": "gateway-gpt-5",
    "gemini-3.1-pro": "gateway-gemini-3-1-pro",
    "deepseek-v4-pro": "gateway-deepseek-v4-pro",
    "deepseek-v4-flash": "gateway-deepseek-v4-flash",
    "grok-4": "gateway-grok-4",
    "kimi-2": "gateway-kimi-2",
}
DEFAULT_MODEL = "gateway-claude-opus-4-7"


console = Console()


def format_model_name(alias: str) -> str:
    return alias.replace("-", " ")

def _safe_print(msg: str) -> None:
    """Print via the current global console. Falls back to plain stdout
    if the console itself is broken (e.g., a half-flushed state after
    a theme change). Never raises."""
    try:
        console.print(msg)
    except Exception:
        try:
            sys.stdout.write(str(msg) + "\n")
            sys.stdout.flush()
        except Exception:
            pass



@dataclass
class Theme:
    name: str
    primary: str = "cyan"
    accent: str = "green"
    error: str = "red"
    warning: str = "yellow"
    prompt: str = "cyan"
    dim: str = "dim"
    header_logo: str = "cyan"
    # Background colors. Hex strings, accepted by Rich and OSC 11 escape.
    background: str = "#0d1117"   # default terminal bg
    prompt_bg: str = "#161b22"    # input area bg
    text_fg: str = "#e6edf3"      # default text fg
    # Visual flavour for the ASCII logo
    logo_left: str = "blue"
    logo_right: str = "green"


THEMES = {
    "dark": Theme(
        "dark",
        primary="cyan", accent="green", error="red", warning="yellow",
        prompt="cyan", dim="bright_black", header_logo="cyan",
        background="#0d1117", prompt_bg="#161b22", text_fg="#e6edf3",
        logo_left="blue", logo_right="green",
    ),
    "hacker": Theme(
        "hacker",
        primary="green", accent="bright_green", error="red", warning="yellow",
        prompt="bright_green", dim="bright_black", header_logo="bright_green",
        background="#0a140a", prompt_bg="#0f2010", text_fg="#a8e6a3",
        logo_left="green", logo_right="bright_green",
    ),
    "neon": Theme(
        "neon",
        primary="magenta", accent="bright_magenta", error="red", warning="yellow",
        prompt="magenta", dim="bright_black", header_logo="bright_magenta",
        background="#1a0033", prompt_bg="#2a0050", text_fg="#e0b0ff",
        logo_left="magenta", logo_right="bright_magenta",
    ),
    "ocean": Theme(
        "ocean",
        primary="blue", accent="bright_blue", error="red", warning="yellow",
        prompt="blue", dim="bright_black", header_logo="bright_blue",
        background="#001f3f", prompt_bg="#003366", text_fg="#a8d8ff",
        logo_left="blue", logo_right="bright_cyan",
    ),
    "sunset": Theme(
        "sunset",
        primary="orange3", accent="bright_red", error="red", warning="yellow",
        prompt="orange3", dim="bright_black", header_logo="orange3",
        background="#2a0a0a", prompt_bg="#3d1414", text_fg="#ffd6a8",
        logo_left="orange3", logo_right="bright_red",
    ),
}


def get_theme(name: str) -> Theme:
    return THEMES.get(name.lower(), THEMES["dark"])


# --- Terminal background control ---------------------------------------------
def set_terminal_background(hex_color: str) -> bool:
    """Try to set the actual terminal background color via OSC 11 escape.

    Supported by: Windows Terminal, ConEmu, iTerm2, kitty, foot, recent
    GNOME Terminal, recent Konsole. No-op on old cmd.exe / older xterms.

    Returns True if the escape was emitted.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return False
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return False
    try:
        sys.stdout.write(f"\x1b]11;rgb:{r:02x}/{g:02x}/{b:02x}\x07")
        # Also reset default fg so theme-aware terminals pick up our text color
        sys.stdout.write(f"\x1b]10;#e6e6e6\x07")
        sys.stdout.flush()
        return True
    except Exception:
        return False


def reset_terminal_colors() -> None:
    """Restore terminal default fg/bg (OSC 10/111)."""
    try:
        sys.stdout.write("\x1b]111\x07\x1b]110\x07")
        sys.stdout.flush()
    except Exception:
        pass


# Module-level console reference. We recreate it when the theme changes so
# that all default text inherits the new background.
console: Console = Console()


def update_console_for_theme(theme: Theme) -> Console:
    """Recreate the global Rich Console with the theme background applied.

    Returns the new Console. Subsequent calls to `console.print(...)` from
    anywhere in this module will use the new background.
    """
    global console
    try:
        console = Console(
            style=f"on {theme.background}",
            force_terminal=True,
            file=sys.stdout,
        )
    except Exception:
        console = Console()
    return console


# --- ASCII logo --------------------------------------------------------------
LOGO_ASCII = r"""
        .--.       .--.
       /    \     /    \
      /      \   /      \
     /        \_/        \
    |          |          |
    |          |          |
     \        | |        /
      \      /   \      /
       \    /     \    /
        '--'       '--'"""


def render_logo(theme: Theme) -> str:
    """Render the ASCII infinity logo with the theme's left/right colors.

    Each line is split in the middle and the left half gets `theme.logo_left`,
    the right half gets `theme.logo_right` — that mimics the blue→green
    gradient of the PNG asset in `assets/logo.png`.
    """
    out_lines = []
    for line in LOGO_ASCII.splitlines():
        if not line.strip():
            out_lines.append(line)
            continue
        mid = len(line) // 2
        left_part = line[:mid]
        right_part = line[mid:]
        out_lines.append(f"[{theme.logo_left}]{left_part}[/{theme.logo_left}]"
                        f"[{theme.logo_right}]{right_part}[/{theme.logo_right}]")
    return "\n".join(out_lines)


def extract_code_blocks(text: str) -> List[Tuple[str, str]]:
    pattern = re.compile(r"```(?:([\w+\-]+)\n)?(.*?)```", re.DOTALL)
    results = []
    for match in pattern.finditer(text):
        lang = (match.group(1) or "").strip().lower()
        code = match.group(2)
        results.append((lang, code))
    return results


LANG_TO_EXT = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "tsx": ".tsx",
    "jsx": ".jsx",
    "html": ".html",
    "css": ".css",
    "json": ".json",
    "yaml": ".yml",
    "yml": ".yml",
    "bash": ".sh",
    "sh": ".sh",
    "bat": ".bat",
    "cmd": ".bat",
    "powershell": ".ps1",
    "ps1": ".ps1",
    "markdown": ".md",
    "md": ".md",
}


def _slugify(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\s.-]", "", s or "").strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return (s or "chat")[:max_len]


def _format_time_ago(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts)
        diff = datetime.now() - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except Exception:
        return iso_ts


def _extract_filename_from_block(lang: str, code: str) -> Optional[str]:
    """Infer a filename from common code-block headers."""
    patterns = [
        r"^\s*#\s*(?:file|filename|path):\s*([^\s]+)\s*$",
        r"^\s*//\s*(?:file|filename|path):\s*([^\s]+)\s*$",
        r"^\s*<!--\s*(?:file|filename|path):\s*([^>]+?)\s*-->\s*$",
        r"^\s*/\*\s*(?:file|filename|path):\s*(.+?)\s*\*/\s*$",
    ]
    for line in code.splitlines()[:5]:
        for pattern in patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                name = match.group(1).strip().strip("`'\"")
                if name:
                    return name

    ext = LANG_TO_EXT.get((lang or "").lower())
    if not ext:
        return None
    return f"snippet{ext}"


def pick_folder_gui(start: str = ".") -> Optional[Path]:
    """Open a native folder-picker dialog. Returns None if the dialog
    can't be opened (no tkinter, no display, or user cancelled)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            folder = filedialog.askdirectory(initialdir=start, title="Select project folder")
        finally:
            try:
                root.destroy()
            except Exception:
                pass
        if folder:
            return Path(folder).resolve()
    except ImportError:
        return None
    except Exception:
        # TclError (no display), Tcl_Obj errors, anything from tkinter
        return None
    return None


SYSTEM_PROMPT = """You are Unlimited Code, an expert AI coding assistant operating inside a user's local project.
You have access to the project folder: {project_folder}

You can use the following tools by emitting XML-like blocks in your response:

<tool>
{{"tool": "read_file", "args": {{"path": "relative/path/from/project"}}}}
</tool>

<tool>
{{"tool": "write_file", "args": {{"path": "relative/path/from/project", "content": "file content here"}}}}
</tool>

<tool>
{{"tool": "list_files", "args": {{"path": "relative/path/from/project", "depth": 2}}}}
</tool>

<tool>
{{"tool": "run_command", "args": {{"command": "shell command to run", "timeout": 60}}}}
</tool>

<tool>
{{"tool": "search_files", "args": {{"query": "text to search", "glob": "*.py"}}}}
</tool>

<tool>
{{"tool": "create_folder", "args": {{"path": "relative/path/from/project"}}}}
</tool>

Rules:
1. ALWAYS prefer using tools when you need to read, write, or inspect project files.
2. Paths are relative to the project root. Do not use absolute paths.
3. When writing files, provide the FULL final content. Do not truncate.
4. If a command is destructive, ask the user for confirmation before running it.
5. Think step by step. Use multiple tool calls if needed.
6. When done, give a final answer in plain text.
7. Use only the tools listed above. Unknown tools will return an error.
8. Keep your final answer concise but complete.
9. If asked to create or edit a file, YOU MUST use the write_file tool.
10. When using write_file, provide the COMPLETE final file content.
11. If the user says "create file X", they want the content saved to X.

Example:
<tool>
{{"tool": "write_file", "args": {{"path": "src/main.py", "content": "print('hello world')"}}}}
</tool>

Current working directory: {project_folder}
"""


TOOLS = {
    "read_file": {"description": "Read a file relative to the project root.", "args": {"path": "string"}},
    "write_file": {"description": "Write a file relative to the project root.", "args": {"path": "string", "content": "string"}},
    "list_files": {"description": "List files recursively.", "args": {"path": "string", "depth": "integer"}},
    "run_command": {"description": "Run a shell command in the project root.", "args": {"command": "string", "timeout": "integer"}},
    "search_files": {"description": "Search text inside files.", "args": {"query": "string", "glob": "string"}},
    "create_folder": {"description": "Create a folder relative to the project root.", "args": {"path": "string"}},
}


class ProjectTools:
    def __init__(self, project_folder: Path):
        self.project_folder = project_folder.resolve()

    def _resolve(self, path: str) -> Path:
        target = (self.project_folder / path).resolve()
        try:
            target.relative_to(self.project_folder)
        except ValueError:
            raise ValueError("Path escapes project folder")
        return target

    def read_file(self, path: str) -> str:
        try:
            target = self._resolve(path)
            if not target.exists():
                return f"[error] File not found: {path}"
            if not target.is_file():
                return f"[error] Not a file: {path}"
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[error] {e}"

    def write_file(self, path: str, content: str) -> str:
        try:
            target = self._resolve(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"[ok] Wrote {path} ({len(content)} chars)"
        except Exception as e:
            return f"[error] {e}"

    def list_files(self, path: str = ".", depth: int = 2) -> str:
        try:
            target = self._resolve(path)
            if not target.exists():
                return f"[error] Path not found: {path}"
            tree = Tree(f" {path}")
            self._build_tree(tree, target, depth)
            return self._tree_to_str(tree)
        except Exception as e:
            return f"[error] {e}"

    def _build_tree(self, tree: Tree, root: Path, depth: int):
        if depth <= 0:
            return
        try:
            entries = sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            tree.add("[permission denied]")
            return
        for entry in entries:
            if entry.is_dir() and entry.name in {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}:
                tree.add(f" {entry.name}/ ...")
                continue
            if entry.is_dir():
                child = tree.add(f" {entry.name}/")
                self._build_tree(child, entry, depth - 1)
            else:
                tree.add(f"📄 {entry.name}")

    def _tree_to_str(self, tree: Tree) -> str:
        lines = []
        self._tree_lines(tree, lines, "")
        return "\n".join(lines)

    def _tree_lines(self, tree, lines, prefix):
        label = str(tree.label)
        lines.append(prefix + label)
        for child in tree.children:
            self._tree_lines(child, lines, prefix + "  ")

    def run_command(self, command: str, timeout: int = 60) -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.project_folder,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr
            output += f"\n[exit code: {result.returncode}]"
            return output
        except subprocess.TimeoutExpired:
            return f"[error] Command timed out after {timeout}s"
        except Exception as e:
            return f"[error] {e}"

    def search_files(self, query: str, glob: str = "*") -> str:
        matches = []
        try:
            for p in self.project_folder.rglob(glob):
                if p.is_file() and p.stat().st_size < 5 * 1024 * 1024:
                    try:
                        text = p.read_text(encoding="utf-8", errors="ignore")
                        if query in text:
                            rel = p.relative_to(self.project_folder)
                            count = text.count(query)
                            matches.append(f"{rel}: {count} match(es)")
                    except Exception:
                        continue
            return "\n".join(matches[:50]) or "[info] No matches found"
        except Exception as e:
            return f"[error] {e}"

    def create_folder(self, path: str) -> str:
        try:
            target = self._resolve(path)
            target.mkdir(parents=True, exist_ok=True)
            return f"[ok] Created folder {path}"
        except Exception as e:
            return f"[error] {e}"

    def execute(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name not in TOOLS:
            return f"[error] Unknown tool: {tool_name}"
        try:
            method = getattr(self, tool_name)
            return method(**args)
        except Exception as e:
            return f"[error] Tool execution failed: {e}"


@dataclass
class Message:
    role: str
    content: str


class ChatStore:
    """Persist chat threads under .unlimited_code/chats in the project."""

    def __init__(self, project_folder: Path):
        self.store_dir = (project_folder / ".unlimited_code" / "chats").resolve()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.store_dir / "index.json"

    def _read_index(self) -> List[Dict[str, Any]]:
        try:
            if not self.index_file.exists():
                return []
            data = json.loads(self.index_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_index(self, items: List[Dict[str, Any]]) -> None:
        try:
            self.index_file.write_text(
                json.dumps(items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def list_chats(self) -> List[Dict[str, Any]]:
        return self._read_index()

    def save(
        self,
        name: str,
        history: List[Message],
        model: str,
        theme: str,
        instructions: str = "",
        chat_id: Optional[str] = None,
    ) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        if chat_id is None:
            chat_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slugify(name)}"

        chat_file = self.store_dir / f"{chat_id}.json"
        existing = self.load(chat_id) or {}
        created_at = existing.get("created_at", now)
        payload = {
            "id": chat_id,
            "name": name,
            "created_at": created_at,
            "updated_at": now,
            "model": model,
            "theme": theme,
            "instructions": instructions,
            "messages": [{"role": m.role, "content": m.content} for m in history],
        }
        chat_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        preview = ""
        for msg in history:
            if msg.role == "user":
                preview = msg.content[:60].replace("\n", " ")
                break

        index = [item for item in self._read_index() if item.get("id") != chat_id]
        index.insert(0, {
            "id": chat_id,
            "name": name,
            "updated_at": now,
            "messages": len(history),
            "preview": preview,
        })
        self._write_index(index)
        return chat_id

    def load(self, chat_id: str) -> Optional[Dict[str, Any]]:
        try:
            chat_file = self.store_dir / f"{chat_id}.json"
            if not chat_file.exists():
                return None
            data = json.loads(chat_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def delete(self, chat_id: str) -> bool:
        try:
            chat_file = self.store_dir / f"{chat_id}.json"
            if chat_file.exists():
                chat_file.unlink()
            index = [item for item in self._read_index() if item.get("id") != chat_id]
            self._write_index(index)
            return True
        except Exception:
            return False

    def rename(self, chat_id: str, new_name: str) -> bool:
        data = self.load(chat_id)
        if not data:
            return False
        now = datetime.now().isoformat(timespec="seconds")
        data["name"] = new_name
        data["updated_at"] = now
        try:
            (self.store_dir / f"{chat_id}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            index = self._read_index()
            for item in index:
                if item.get("id") == chat_id:
                    item["name"] = new_name
                    item["updated_at"] = now
            self._write_index(index)
            return True
        except Exception:
            return False


class UnlimitedClient:
    def __init__(self, api_key: str, model: str, project_folder: Path):
        self.api_key = api_key
        self.model = model
        self.project_folder = project_folder
        self.history: List[Message] = []
        self.extra_instructions: str = ""
        self.debug_mode: bool = False
        self.effort: str = "low"
        self.system = self._build_system()
        self.tools = ProjectTools(project_folder)
        self.client = httpx.Client(timeout=180.0)

    def _build_system(self) -> str:
        base = SYSTEM_PROMPT.format(project_folder=str(self.project_folder))
        try:
            tree_lines = []
            skip_dirs = {
                ".git", "node_modules", "__pycache__", ".venv", "venv",
                "dist", "build", ".unlimited_code", ".next", ".idea", ".vscode",
            }
            for entry in sorted(self.project_folder.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if entry.name.startswith(".") and entry.name not in (".env", ".env.example"):
                    continue
                if entry.is_dir():
                    if entry.name in skip_dirs:
                        tree_lines.append(f"  {entry.name}/ (skipped)")
                        continue
                    tree_lines.append(f"  {entry.name}/")
                    try:
                        for sub in sorted(entry.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:20]:
                            if sub.is_file():
                                tree_lines.append(f"    {sub.name}")
                    except Exception:
                        pass
                else:
                    try:
                        tree_lines.append(f"  {entry.name} ({entry.stat().st_size} bytes)")
                    except Exception:
                        tree_lines.append(f"  {entry.name}")
            if tree_lines:
                base += "\n\n[CURRENT PROJECT STRUCTURE]\n" + "\n".join(tree_lines)
        except Exception:
            pass
        if self.extra_instructions:
            base += f"\n\n[ADDITIONAL USER INSTRUCTIONS]\n{self.extra_instructions}"
        return base

    def chat(self, user_input: str) -> str:
        self.history.append(Message(role="user", content=user_input))
        return self._agent_loop()

    def _agent_loop(self, max_iterations: int = 25) -> str:
        force_reminder_sent = False
        for _ in range(max_iterations):
            response_text = self._stream_completion()
            tool_calls = self._parse_tool_calls(response_text)
            if not tool_calls:
                last_user = self.history[-1].content if self.history else ""
                if not force_reminder_sent and self._looks_like_file_request(last_user):
                    force_reminder_sent = True
                    self.history.append(Message(role="assistant", content=response_text))
                    self.history.append(Message(
                        role="user",
                        content="You did not use a tool. The user asked for a file. You MUST create it with the write_file tool NOW."
                    ))
                    continue
                self.history.append(Message(role="assistant", content=response_text))
                return response_text
            force_reminder_sent = False
            self.history.append(Message(role="assistant", content=response_text))
            for tool_name, args in tool_calls:
                console.print(f"[dim]→ running tool: {tool_name}({json.dumps(args, ensure_ascii=False)[:200]})[/dim]")
                result = self.tools.execute(tool_name, args)
                if len(result) > 8000:
                    result = result[:8000] + "\n... [truncated]"
                self.history.append(Message(role="user", content=f"[tool result: {tool_name}]\n{result}"))
        return "[error] Too many tool iterations."

    def _looks_like_file_request(self, text: str) -> bool:
        t = text.lower()
        keywords = [
            "создай файл", "создать файл", "напиши файл", "сделай файл",
            "create file", "write file", "make file", "создай .bat", "создай bat",
            "create bat", "write bat", "edit file", "измени файл", "добавь файл",
        ]
        return any(k in t for k in keywords)

    def _stream_completion(self) -> str:
        messages = [{"role": "system", "content": self.system}]
        for m in self.history:
            messages.append({"role": m.role, "content": m.content})
        transcript_lines = []
        for msg in messages[:-1]:
            transcript_lines.append(f"{msg['role'].upper()}:\n{msg['content']}")
        if transcript_lines:
            message_text = (
                "[CONVERSATION SO FAR]\n"
                + "\n\n".join(transcript_lines[-40:])
                + "\n\n[CURRENT USER MESSAGE]\n"
                + messages[-1]["content"]
            )
        else:
            message_text = messages[-1]["content"]
        payload = {
            "message": message_text,
            "model": self.model,
            "effort": self.effort,
            "history": messages[:-1],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.debug_mode:
            console.print("[dim magenta]─── DEBUG PAYLOAD ───[/dim magenta]")
            console.print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        try:
            return self._do_stream(payload, headers)
        except RuntimeError as e:
            err_str = str(e).lower()
            if "history" in err_str or "400" in err_str or "422" in err_str:
                console.print("[dim]Falling back to single-message mode[/dim]")
                fallback = {
                    "message": message_text,
                    "model": self.model,
                    "effort": self.effort,
                }
                return self._do_stream(fallback, headers)
            raise

    def _do_stream(self, payload: Dict[str, Any], headers: Dict[str, str]) -> str:
        collected = []
        with self.client.stream("POST", CHAT_ENDPOINT, json=payload, headers=headers) as response:
            if response.status_code != 200:
                try:
                    err = response.json()
                except Exception:
                    err = response.text
                raise RuntimeError(f"API error {response.status_code}: {err}")
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    line = line.decode("utf-8") if isinstance(line, bytes) else line
                except Exception:
                    continue
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    frame = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(frame, dict):
                    continue
                if "delta" in frame and frame["delta"]:
                    piece = str(frame["delta"])
                    collected.append(piece)
                    try:
                        console.print(piece, end="")
                    except Exception:
                        # If Rich has trouble (e.g., partial UTF-8), fallback
                        try:
                            sys.stdout.write(piece)
                            sys.stdout.flush()
                        except Exception:
                            pass
        try:
            console.print()
        except Exception:
            try:
                sys.stdout.write("\n")
                sys.stdout.flush()
            except Exception:
                pass
        return "".join(collected)

    def _parse_tool_calls(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        calls = []
        pattern = re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.DOTALL)
        for match in pattern.finditer(text):
            try:
                obj = json.loads(match.group(1))
                if "tool" in obj and "args" in obj:
                    calls.append((obj["tool"], obj["args"]))
            except json.JSONDecodeError:
                continue
        code_pattern = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
        for match in code_pattern.finditer(text):
            try:
                obj = json.loads(match.group(1))
                if "tool" in obj and "args" in obj:
                    calls.append((obj["tool"], obj["args"]))
            except json.JSONDecodeError:
                continue
        for obj in self._extract_json_objects(text):
            if isinstance(obj, dict) and "tool" in obj and "args" in obj:
                calls.append((obj["tool"], obj["args"]))
        return calls

    def _extract_json_objects(self, text: str) -> List[Any]:
        results = []
        i = 0
        while i < len(text):
            if text[i] == '{':
                start = i
                depth = 1
                i += 1
                while i < len(text) and depth > 0:
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                    i += 1
                if depth == 0:
                    try:
                        results.append(json.loads(text[start:i]))
                    except json.JSONDecodeError:
                        pass
            else:
                i += 1
        return results

    def simple_chat(self, prompt: str) -> str:
        payload = {
            "message": self.system + "\n\n" + prompt,
            "model": self.model,
            "effort": self.effort,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        return self._do_stream(payload, headers)

    def reset(self):
        self.history.clear()


class UnlimitedCodeApp:
    def __init__(self, project_folder: Path, model: str):
        if not API_KEY:
            console.print("[bold red]Error:[/bold red] UNLIMITED_API_KEY not set. Add it to .env or export it.")
            sys.exit(1)
        self.project_folder = project_folder.resolve()
        self.model = model
        self.default_language: str = os.environ.get("UNLIMITED_DEFAULT_LANG", "")
        self.theme = get_theme(os.environ.get("UNLIMITED_THEME", "dark"))
        autosave_env = os.environ.get("UNLIMITED_AUTOSAVE", "1").strip().lower()
        self.auto_save: bool = autosave_env not in ("0", "false", "no", "off")
        self.client = UnlimitedClient(API_KEY, model, self.project_folder)
        try:
            self.chat_store = ChatStore(self.project_folder)
        except Exception:
            self.chat_store = None
        self.current_chat_id: Optional[str] = None
        self.current_chat_name: str = "untitled"
        self.resumed_chat: bool = False
        try:
            if self.chat_store and not os.environ.get("UNLIMITED_NO_AUTORESUME"):
                chats = self.chat_store.list_chats()
                if chats:
                    self.resumed_chat = self._resume_chat(chats[0]["id"])
        except Exception:
            pass
        self._apply_theme()

    def _create_session(self):
        color_map = {
            "cyan": "ansicyan",
            "green": "ansigreen",
            "bright_green": "ansigreen",
            "magenta": "ansimagenta",
            "bright_magenta": "ansimagenta",
            "blue": "ansiblue",
            "bright_blue": "ansiblue",
            "orange3": "ansiyellow",
            "bright_red": "ansired",
            "red": "ansired",
            "yellow": "ansiyellow",
        }
        prompt_color = color_map.get(self.theme.prompt, "ansicyan")
        bg = self.theme.prompt_bg
        fg = self.theme.text_fg
        self.session = PromptSession(
            completer=WordCompleter([
                "/model", "/folder", "/files", "/pick", "/setup-bat", "/fun-bat",
                "/create", "/edit", "/project", "/models", "/mkdir", "/default-lang", "/speed", "/theme",
                "/newchat", "/reset", "/instructions", "/debug", "/autosave", "/chats", "/chathistory",
                "/help", "/exit", "exit", "quit",
                "read_file", "write_file", "list_files", "run_command", "search_files", "create_folder"
            ]),
            style=Style.from_dict({
                # Default: paint the whole input area with the theme bg
                "": f"bg:{bg} fg:{fg}",
                "prompt": f"bg:{bg} {prompt_color} bold",
                "prompt-arrow": f"bg:{bg} {prompt_color} bold",
                "completion-menu": f"bg:{bg} fg:{fg} border:{prompt_color}",
                "completion-menu.completion.current": f"bg:{prompt_color} fg:{bg} bold",
                "completion-menu.completion": f"bg:{bg} fg:{fg}",
                "scrollbar.background": f"bg:{bg}",
                "scrollbar.button": f"bg:{prompt_color}",
            }),
        )

    def _apply_theme(self):
        """Apply the current theme. Every step is wrapped so a theme
        switch can never kill the app — even on broken terminals."""
        try:
            update_console_for_theme(self.theme)
        except Exception as e:
            _safe_print(f"[yellow]Console theme update failed: {e}[/yellow]")
        try:
            set_terminal_background(self.theme.background)
        except Exception:
            pass
        try:
            self._set_window_title(f"Unlimited Code - {self.theme.name}")
        except Exception:
            pass
        try:
            self._create_session()
        except Exception as e:
            _safe_print(f"[yellow]Prompt theme update failed: {e}[/yellow]")

    def _set_window_title(self, title: str):
        """Set console window title. ASCII-safe everywhere."""
        try:
            ascii_title = title.encode("ascii", "replace").decode("ascii")
        except Exception:
            ascii_title = "Unlimited Code"
        if sys.platform == "win32":
            try:
                os.system(f"title {ascii_title}")
            except Exception:
                pass
        else:
            try:
                sys.stdout.write(f"\x1b]0;{ascii_title}\x07")
                sys.stdout.flush()
            except Exception:
                pass

    def run(self):
        try:
            with console.status(f"[bold {self.theme.accent}] Loading Unlimited Code...[/bold {self.theme.accent}]", spinner="dots"):
                time.sleep(0.3)
        except Exception:
            pass
        self._print_header()
        while True:
            try:
                text = self.session.prompt("unlimited> ")
            except (KeyboardInterrupt, EOFError):
                _safe_print("\n[dim] Goodbye[/dim]")
                break
            except Exception as e:
                _safe_print(f"[yellow]Prompt error (recovering): {e}[/yellow]")
                continue
            text = text.strip()
            if not text:
                continue
            try:
                if self._handle_command(text):
                    try:
                        self._auto_save_chat()
                    except Exception:
                        pass
                    continue
            except (KeyboardInterrupt, EOFError, SystemExit):
                raise
            except Exception as e:
                _safe_print(f"[bold {self.theme.error}] Command error: {self.theme.error} {e}[/{self.theme.error}]")
                continue
            try:
                if self._looks_like_project_request(text):
                    self._create_project(self._extract_project_description(text))
                else:
                    filename = self._extract_filename_from_request(text)
                    if filename:
                        self._auto_create_file(filename, text)
                    else:
                        try:
                            with console.status(f"[bold {self.theme.accent}] Thinking...[/bold {self.theme.accent}]"):
                                answer = self.client.chat(text)
                        except (KeyboardInterrupt, EOFError):
                            _safe_print("[dim] Cancelled.[/dim]")
                            continue
                        except Exception as e:
                            _safe_print(f"[bold red] Chat failed: {e}[/bold red]")
                            continue
                        if answer:
                            t = self.theme
                            try:
                                console.print(Panel(answer, title=" Unlimited Code", border_style=t.primary, box=box.ROUNDED))
                            except Exception as ex:
                                _safe_print(f"[yellow]Could not render response panel: {ex}[/yellow]")
                                _safe_print(answer)
                            try:
                                self._offer_save_code(answer)
                            except (KeyboardInterrupt, EOFError):
                                pass
                            except Exception as ex:
                                _safe_print(f"[yellow]Save prompt failed: {ex}[/yellow]")
                            try:
                                self._auto_save_chat()
                            except Exception:
                                pass
            except (KeyboardInterrupt, EOFError, SystemExit):
                raise
            except Exception as e:
                _safe_print(f"[bold {self.theme.error}] Error:[/bold {self.theme.error}] {e}")

    def _print_header(self):
        try:
            self._set_window_title(f"Unlimited Code - {self.theme.name}")
        except Exception:
            pass
        t = self.theme
        try:
            logo = render_logo(t)
            chat_line = ""
            if self.current_chat_name and self.current_chat_name != "untitled":
                chat_line = (
                    f"\n Chat:    [{t.accent}]{self.current_chat_name}[/{t.accent}]"
                    f" ({len(self.client.history)} msgs)"
                )
            save_line = f"\n Autosave: [{'green' if self.auto_save else 'yellow'}]{'ON' if self.auto_save else 'OFF'}[/]"
            body = (
                f"[bold {t.header_logo}]UNLIMITED CODE[/bold {t.header_logo}]\n"
                f"[{t.dim}]AI Coding Agent for your local projects[/{t.dim}]\n\n"
                f" {logo}\n\n"
                f" Project: [{t.primary}]{self.project_folder}[/{t.primary}]\n"
                f" Model:   [{t.primary}]{format_model_name(self._model_alias())}[/{t.primary}]\n"
                f" Theme:   [{t.accent}]{self.theme.name}[/{t.accent}]    Type [bold]/help[/bold] for commands."
                + save_line
                + chat_line
            )
            console.print(Panel(
                body,
                title=f" {self.theme.name.upper()} ",
                border_style=t.accent,
                box=box.DOUBLE,
                padding=(1, 2),
            ))
        except Exception as e:
            _safe_print(f"[yellow]Header render failed: {e}[/yellow]")
        if LOGO_PATH.exists():
            _safe_print(f"[dim]Logo: {LOGO_PATH}[/dim]")

    def _model_alias(self) -> str:
        for alias, model_id in AVAILABLE_MODELS.items():
            if model_id == self.model:
                return alias
        return self.model

    def _set_model(self, alias: str):
        new_model = AVAILABLE_MODELS[alias]
        # preserve settings
        old_extra = self.client.extra_instructions
        old_debug = self.client.debug_mode
        old_effort = self.client.effort
        old_history = list(self.client.history)
        self.model = new_model
        self.client = UnlimitedClient(API_KEY, new_model, self.project_folder)
        self.client.history = old_history
        self.client.extra_instructions = old_extra
        self.client.debug_mode = old_debug
        self.client.effort = old_effort
        self.client.system = self.client._build_system()
        console.print(f"[bold green] Model set to {format_model_name(alias)}[/bold green]")

    def _interactive_model_select(self):
        t = self.theme
        items = list(AVAILABLE_MODELS.items())
        try:
            console.print(f"[bold {t.accent}] Available models:[/bold {t.accent}]")
            for i, (alias, _) in enumerate(items, 1):
                marker = "→" if alias == self._model_alias() else " "
                console.print(f" [{t.primary}]{marker} {i}. {format_model_name(alias)}[/{t.primary}]")
            choice = self.session.prompt("Select model (number or name): ")
        except (KeyboardInterrupt, EOFError):
            return
        except Exception as e:
            _safe_print(f"[yellow]Model selection unavailable: {e}[/yellow]")
            return
        choice = choice.strip()
        if not choice:
            return
        try:
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(items):
                    self._set_model(items[idx][0])
                    return
            if choice in AVAILABLE_MODELS:
                self._set_model(choice)
            else:
                _safe_print(f"[red] Unknown choice: {choice}[/red]")
        except Exception as e:
            _safe_print(f"[red] Failed to switch model: {e}[/red]")

    def _interactive_theme_select(self):
        t = self.theme
        try:
            console.print(f"[bold {t.accent}] Available themes:[/bold {t.accent}]")
            for i, name in enumerate(THEMES.keys(), 1):
                marker = "→" if name == self.theme.name else " "
                console.print(f" [{t.primary}]{marker} {i}. {name}[/{t.primary}]")
            choice = self.session.prompt("Select theme (number or name): ")
        except (KeyboardInterrupt, EOFError):
            return
        except Exception as e:
            _safe_print(f"[yellow]Theme selection unavailable: {e}[/yellow]")
            return
        choice = choice.strip()
        if not choice:
            return
        try:
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(THEMES):
                    self.theme = get_theme(list(THEMES.keys())[idx])
                    self._apply_theme()
                    _safe_print(f"[bold green] Theme set to {self.theme.name}[/bold green]")
                    return
            if choice.lower() in THEMES:
                self.theme = get_theme(choice.lower())
                self._apply_theme()
                _safe_print(f"[bold green] Theme set to {self.theme.name}[/bold green]")
            else:
                _safe_print(f"[red] Unknown theme: {choice}[/red]")
        except Exception as e:
            _safe_print(f"[red] Failed to switch theme: {e}[/red]")

    def _print_models(self):
        t = self.theme
        console.print(f"[bold {t.accent}] Available models:[/bold {t.accent}]")
        for alias, model_id in AVAILABLE_MODELS.items():
            marker = "→" if model_id == self.model else " "
            console.print(f" [{t.primary}]{marker} {format_model_name(alias)}[/{t.primary}] [dim]{model_id}[/dim]")

    def _print_help(self):
        t = self.theme
        help_text = f"""
[bold {t.accent}]/model[/bold {t.accent}] — select model
[bold {t.accent}]/theme[/bold {t.accent}] — select theme
[bold {t.accent}]/folder <path>[/bold {t.accent}] — change project folder
[bold {t.accent}]/pick[/bold {t.accent}] — open GUI folder picker
[bold {t.accent}]/files [path] [depth][/bold {t.accent}] — list project files
[bold {t.accent}]/setup-bat[/bold {t.accent}] — create Windows launcher
[bold {t.accent}]/fun-bat <name>[/bold {t.accent}] — create fun .bat file
[bold {t.accent}]/create <path> <description>[/bold {t.accent}] — generate and save a file
[bold {t.accent}]/edit <path> <description>[/bold {t.accent}] — edit an existing file
[bold {t.accent}]/project <description>[/bold {t.accent}] — create multiple files
[bold {t.accent}]/mkdir <path>[/bold {t.accent}] — create a folder
[bold {t.accent}]/default-lang <language>[/bold {t.accent}] — set default language
[bold {t.accent}]/models[/bold {t.accent}] — list models from API
[bold {t.accent}]/speed <low|medium|high>[/bold {t.accent}] — set speed
[bold {t.accent}]/newchat[/bold {t.accent}] — start new chat
[bold {t.accent}]/reset[/bold {t.accent}] — clear chat history
[bold {t.accent}]/instructions <text>[/bold {t.accent}] — add instructions
[bold {t.accent}]/debug[/bold {t.accent}] — toggle debug mode
[bold {t.accent}]/help[/bold {t.accent}] — show this message
[bold {t.accent}]exit / quit[/bold {t.accent}] — close the app
"""
        console.print(Panel(help_text, title=" Commands", border_style=t.accent, box=box.ROUNDED))

    def _handle_command(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        parts = text.split()
        if not parts:
            return False
        cmd = parts[0].lower()
        if cmd in ("/exit", "exit", "quit", "/quit"):
            console.print("[dim] Goodbye[/dim]")
            sys.exit(0)
        if cmd == "/help":
            self._print_help()
            return True
        if cmd == "/reset":
            try:
                self._auto_save_chat()
            except Exception:
                pass
            self.client.reset()
            self.client.extra_instructions = ""
            self.client.system = self.client._build_system()
            self.current_chat_id = None
            self.current_chat_name = "untitled"
            console.print("[dim] Chat history reset. Previous chat was auto-saved.[/dim]")
            return True
        if cmd == "/newchat":
            try:
                self._auto_save_chat()
            except Exception:
                pass
            self.client.reset()
            self.current_chat_id = None
            self.current_chat_name = "untitled"
            console.print("[dim] New chat started. Previous one is in /chats list.[/dim]")
            return True
        if cmd == "/instructions":
            if len(parts) < 2:
                if self.client.extra_instructions:
                    console.print(Panel(self.client.extra_instructions, title=" Instructions", border_style="magenta", box=box.ROUNDED))
                else:
                    console.print("[dim]No instructions set. Use /instructions <text>.[/dim]")
                return True
            instr = " ".join(parts[1:])
            self.client.extra_instructions = instr
            self.client.system = self.client._build_system()
            preview = instr[:80] + ('...' if len(instr) > 80 else '')
            console.print(f"[dim] Added instructions: {preview}[/dim]")
            return True
        if cmd == "/debug":
            self.client.debug_mode = not self.client.debug_mode
            console.print(f"[dim] Debug mode: {'ON' if self.client.debug_mode else 'OFF'}[/dim]")
            return True
        if cmd == "/files":
            path = parts[1] if len(parts) > 1 else "."
            depth = int(parts[2]) if len(parts) > 2 else 2
            console.print(self.client.tools.list_files(path, depth))
            return True
        if cmd == "/model":
            if len(parts) < 2:
                self._interactive_model_select()
                return True
            alias = parts[1]
            if alias in AVAILABLE_MODELS:
                self._set_model(alias)
            else:
                console.print(f"[red] Unknown model: {alias}[/red]")
                self._interactive_model_select()
            return True
        if cmd == "/theme":
            if len(parts) < 2:
                self._interactive_theme_select()
                return True
            choice = parts[1].strip()
            name = None
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(THEMES):
                    name = list(THEMES.keys())[idx]
            elif choice.lower() in THEMES:
                name = choice.lower()
            if name:
                self.theme = get_theme(name)
                self._apply_theme()
                console.print(f"[bold green] Theme set to {name}[/bold green]")
            else:
                console.print(f"[red] Unknown theme: {choice}[/red]")
                self._interactive_theme_select()
            return True
        if cmd == "/folder":
            if len(parts) < 2:
                console.print(f"[dim] Current folder: {self.project_folder}[/dim]")
                return True
            new_path = Path(" ".join(parts[1:])).expanduser().resolve()
            if not new_path.exists():
                console.print(f"[red] Folder not found: {new_path}[/red]")
                return True
            self._set_folder(new_path)
            return True
        if cmd == "/pick":
            try:
                chosen = pick_folder_gui(str(self.project_folder))
            except Exception as e:
                _safe_print(f"[red] Folder picker error: {e}[/red]")
                return True
            if chosen:
                self._set_folder(chosen)
            else:
                _safe_print("[dim]No folder selected (GUI unavailable or cancelled).[/dim]")
            return True
        if cmd == "/setup-bat":
            self._setup_bat()
            return True
        if cmd == "/fun-bat":
            if len(parts) < 2:
                self._list_fun_bats()
                return True
            self._create_fun_bat(parts[1])
            return True
        if cmd == "/create":
            if len(parts) < 2:
                console.print("[red] Usage: /create <path> <description>[/red]")
                return True
            self._create_file(parts[1], " ".join(parts[2:]) if len(parts) > 2 else "")
            return True
        if cmd == "/edit":
            if len(parts) < 2:
                console.print("[red] Usage: /edit <path> <description>[/red]")
                return True
            self._edit_file(parts[1], " ".join(parts[2:]) if len(parts) > 2 else "")
            return True
        if cmd == "/project":
            self._create_project(" ".join(parts[1:]) if len(parts) > 1 else "")
            return True
        if cmd == "/models":
            self._list_models()
            return True
        if cmd == "/mkdir":
            if len(parts) < 2:
                console.print("[red] Usage: /mkdir <path>[/red]")
                return True
            console.print(self.client.tools.create_folder(parts[1]))
            return True
        if cmd == "/default-lang":
            if len(parts) < 2:
                if self.default_language:
                    console.print(f"[dim] Default language: {self.default_language}[/dim]")
                else:
                    console.print("[dim]No default language set. Use /default-lang <language>.[/dim]")
                return True
            self.default_language = parts[1]
            console.print(f"[dim] Default language set to: {self.default_language}[/dim]")
            return True
        if cmd == "/speed":
            if len(parts) < 2:
                console.print(f"[dim] Current speed: {self.client.effort}[/dim]")
                return True
            mode = parts[1].lower()
            if mode in ("low", "medium", "high"):
                self.client.effort = mode
                console.print(f"[dim] Speed set to {mode}[/dim]")
            else:
                console.print("[red] Use low, medium, or high[/red]")
            return True
        if cmd == "/autosave":
            if len(parts) < 2:
                state = "ON" if self.auto_save else "OFF"
                _safe_print(f"[dim] Auto-save is {state}. Use /autosave on|off[/dim]")
                return True
            value = parts[1].lower()
            if value in ("on", "1", "true", "yes", "enable"):
                self.auto_save = True
                _safe_print("[bold green] Auto-save: ON[/bold green]")
            elif value in ("off", "0", "false", "no", "disable"):
                self.auto_save = False
                _safe_print("[bold yellow] Auto-save: OFF[/bold yellow]")
            else:
                _safe_print("[red] Use /autosave on|off[/red]")
            return True
        if cmd in ("/chats", "/chathistory"):
            return self._handle_chats_command(parts)
        return False

    def _set_folder(self, new_path: Path):
        try:
            self.project_folder = new_path
            self.client.project_folder = new_path
            self.client.tools.project_folder = new_path
            self.client.system = self.client._build_system()
            try:
                self.chat_store = ChatStore(new_path)
                self.current_chat_id = None
                self.current_chat_name = "untitled"
            except Exception:
                self.chat_store = None
            _safe_print(f"[dim] Switched to folder: {new_path}[/dim]")
        except Exception as e:
            _safe_print(f"[red] Failed to switch folder: {e}[/red]")

    def _auto_save_chat(self) -> None:
        if not self.chat_store or not self.client.history:
            return
        name = self.current_chat_name or "untitled"
        if name == "untitled":
            for msg in self.client.history:
                if msg.role == "user":
                    name = msg.content[:40].strip() or "untitled"
                    self.current_chat_name = name
                    break
        self.current_chat_id = self.chat_store.save(
            name=name,
            history=self.client.history,
            model=self.model,
            theme=self.theme.name,
            instructions=self.client.extra_instructions,
            chat_id=self.current_chat_id,
        )

    def _resume_chat(self, chat_id: str) -> bool:
        data = self.chat_store.load(chat_id) if self.chat_store else None
        if not data:
            return False
        try:
            old_debug = self.client.debug_mode
            old_effort = self.client.effort
            messages = []
            for item in data.get("messages", []):
                if isinstance(item, dict) and item.get("role") and item.get("content") is not None:
                    messages.append(Message(role=str(item["role"]), content=str(item["content"])))

            model_id = data.get("model")
            if model_id and model_id in AVAILABLE_MODELS.values():
                self.model = model_id
                self.client = UnlimitedClient(API_KEY, model_id, self.project_folder)
                self.client.debug_mode = old_debug
                self.client.effort = old_effort

            self.client.history = messages
            self.current_chat_id = chat_id
            self.current_chat_name = data.get("name", "untitled")
            if data.get("theme") in THEMES:
                self.theme = get_theme(data["theme"])
            if data.get("instructions"):
                self.client.extra_instructions = data["instructions"]
            self.client.system = self.client._build_system()
            return True
        except Exception as e:
            _safe_print(f"[red] Failed to resume chat: {e}[/red]")
            return False

    def _list_chats_human(self) -> str:
        if not self.chat_store:
            return "[red] Chat store unavailable.[/red]"
        chats = self.chat_store.list_chats()
        if not chats:
            return "[dim]No saved chats yet.[/dim]"
        rows = ["  active  id                              name                           msgs  when",
                "  " + "-" * 74]
        for item in chats[:30]:
            active = ">" if item.get("id") == self.current_chat_id else " "
            rows.append(
                f"  {active}      {item.get('id', '?'):<30} "
                f"{(item.get('name') or 'untitled')[:30]:<30} "
                f"{item.get('messages', 0):>4}  "
                f"{_format_time_ago(item.get('updated_at', ''))}"
            )
        if len(chats) > 30:
            rows.append(f"  ... and {len(chats) - 30} more")
        return "\n".join(rows)

    def _handle_chats_command(self, parts: List[str]) -> bool:
        if not self.chat_store:
            _safe_print("[red] Chat store unavailable (cannot write .unlimited_code/chats).[/red]")
            return True
        sub = parts[1].lower() if len(parts) > 1 else "list"
        if sub in ("list", ""):
            console.print(f"[bold {self.theme.accent}]Saved chats:[/bold {self.theme.accent}]")
            console.print(self._list_chats_human())
            console.print("[dim]Commands: /chats switch <id> | save [name] | rename <name> | delete <id> | new[/dim]")
            return True
        if sub == "save":
            name = " ".join(parts[2:]).strip() if len(parts) > 2 else self.current_chat_name
            if not name or name == "untitled":
                for msg in self.client.history:
                    if msg.role == "user":
                        name = msg.content[:40].strip()
                        break
            self.current_chat_name = name or "untitled"
            self._auto_save_chat()
            console.print(f"[bold green] Saved chat:[/bold green] {self.current_chat_name}  id: {self.current_chat_id}")
            return True
        if sub == "switch":
            if len(parts) < 3:
                console.print("[red] Usage: /chats switch <id-or-name-part>[/red]")
                return True
            target = parts[2].lower()
            match = None
            for item in self.chat_store.list_chats():
                item_id = item.get("id", "")
                item_name = item.get("name", "")
                if target == item_id.lower() or target in item_id.lower() or target in item_name.lower():
                    match = item_id
                    break
            if not match:
                console.print(f"[red] No chat matching: {parts[2]}[/red]")
                return True
            self._auto_save_chat()
            if self._resume_chat(match):
                console.print(f"[bold green] Switched to chat:[/bold green] {self.current_chat_name}")
            return True
        if sub == "rename":
            if len(parts) < 3:
                console.print("[red] Usage: /chats rename <new-name>[/red]")
                return True
            new_name = " ".join(parts[2:]).strip()
            if not self.current_chat_id:
                self._auto_save_chat()
            if self.current_chat_id and self.chat_store.rename(self.current_chat_id, new_name):
                self.current_chat_name = new_name
                console.print(f"[bold green] Renamed to:[/bold green] {new_name}")
            else:
                console.print("[red] Failed to rename.[/red]")
            return True
        if sub == "delete":
            if len(parts) < 3:
                console.print("[red] Usage: /chats delete <id-or-part>[/red]")
                return True
            target = parts[2].lower()
            match = None
            for item in self.chat_store.list_chats():
                item_id = item.get("id", "")
                if target == item_id.lower() or target in item_id.lower():
                    match = item_id
                    break
            if not match:
                console.print(f"[red] No chat matching: {parts[2]}[/red]")
                return True
            if self.chat_store.delete(match):
                console.print(f"[bold yellow] Deleted:[/bold yellow] {match}")
                if match == self.current_chat_id:
                    self.current_chat_id = None
                    self.current_chat_name = "untitled"
                    self.client.reset()
            return True
        if sub == "new":
            self._auto_save_chat()
            self.client.reset()
            self.current_chat_id = None
            self.current_chat_name = "untitled"
            console.print("[dim] New chat. Previous one is in /chats list.[/dim]")
            return True
        console.print(f"[red] Unknown /chats subcommand: {sub}[/red]")
        return True

    def _setup_bat(self):
        project_bat = self.project_folder / "unlimited_code.bat"
        script_path = Path(__file__).resolve()
        venv_dir = script_path.parent / ".venv"
        if sys.platform == "win32":
            activate = (venv_dir / "Scripts" / "activate.bat").resolve()
        else:
            activate = (venv_dir / "bin" / "activate").resolve()
        bat_content = f'''@echo off
:: Unlimited Code launcher
:: Reads UNLIMITED_API_KEY and UNLIMITED_BASE_URL from .env in this folder
cd /d "%~dp0"
if exist .env (
  for /f "usebackq tokens=1,2 delims==" %%a in (.env) do (
    if not "%%a"=="" set "%%a=%%b"
  )
)
call "{activate}" >nul 2>&1
python "{script_path}" "%~dp0"
if errorlevel 1 pause
'''
        project_bat.write_text(bat_content, encoding="utf-8")
        console.print(f"[bold green] Created launcher:[/bold green] {project_bat}")
        console.print("[dim]Launcher reads key from .env — no hardcoded secret.[/dim]")

    def _fun_bats_dir(self) -> Path:
        return Path(__file__).resolve().parent / "fun_bats"

    def _list_fun_bats(self):
        bats_dir = self._fun_bats_dir()
        if not bats_dir.exists():
            console.print("[red] fun_bats templates not found.[/red]")
            return
        console.print("[bold] Available fun .bat files:[/bold]")
        for f in sorted(bats_dir.glob("*.bat")):
            console.print(f" • {f.stem}")
        console.print("\n[dim]Usage: /fun-bat <name>[/dim]")

    def _create_fun_bat(self, name: str):
        bats_dir = self._fun_bats_dir()
        if not bats_dir.exists():
            console.print("[red] fun_bats templates not found.[/red]")
            return
        src = bats_dir / f"{name}.bat"
        if not src.exists():
            console.print(f"[red] Template not found: {name}.bat[/red]")
            self._list_fun_bats()
            return
        dst = self.project_folder / f"{name}.bat"
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        console.print(f"[bold green] Created fun bat:[/bold green] {dst}")

    def _create_file(self, path: str, description: str):
        if not description:
            description = f"Create a complete, working file named {path}"
        prompt = (
            f"Create a file at `{path}` in the project folder.\n"
            f"Task: {description}\n\n"
            f"IMPORTANT: Do NOT use any tools. Do NOT use write_file.\n"
            f"Respond ONLY with the complete file content inside a markdown code block.\n"
            f"The response MUST start with ``` and end with ```."
        )
        with console.status(f"[bold {self.theme.accent}] Generating file...[/bold {self.theme.accent}]"):
            response = self.client.simple_chat(prompt)
        blocks = extract_code_blocks(response)
        if blocks:
            content = blocks[0][1]
        else:
            content = response.strip()
        result = self.client.tools.write_file(path, content)
        console.print(f"[bold green] {result}[/bold green]")

    def _edit_file(self, path: str, description: str):
        current = self.client.tools.read_file(path)
        if current.startswith("[error]"):
            console.print(f"[red]{current}[/red]")
            return
        if not description:
            description = "improve or update the file"
        prompt = (
            f"Here is the current content of `{path}`:\n\n```\n{current}\n```\n\n"
            f"Please {description}.\n\n"
            f"IMPORTANT: Do NOT use any tools. Do NOT use write_file.\n"
            f"Respond ONLY with the complete new file content inside a markdown code block.\n"
            f"The response MUST start with ``` and end with ```."
        )
        with console.status(f"[bold {self.theme.accent}] Editing file...[/bold {self.theme.accent}]"):
            response = self.client.simple_chat(prompt)
        blocks = extract_code_blocks(response)
        if blocks:
            content = blocks[0][1]
        else:
            content = response.strip()
        result = self.client.tools.write_file(path, content)
        console.print(f"[bold green] {result}[/bold green]")

    def _create_project(self, description: str):
        if not description.strip():
            console.print("[yellow] What project should I create?[/yellow]")
            console.print("[dim]Examples: calculator, todo app, snake game, weather API[/dim]")
            return
        lang_hint = ""
        if self.default_language:
            lang_hint = f" Use {self.default_language} as the primary language unless specified otherwise."
        prompt = (
            f"Create a complete project described as: {description}{lang_hint}\n\n"
            f"Return ONLY a JSON array of objects. Each object must have:\n"
            f'- "path": relative file path inside the project\n'
            f'- "content": complete file content as a string\n\n'
            f"Wrap the JSON in a markdown code block: ```json ... ```\n"
            f"Do NOT include explanations, only the JSON array."
        )
        with console.status(f"[bold {self.theme.accent}] Creating project...[/bold {self.theme.accent}]"):
            response = self.client.simple_chat(prompt)
        json_text = None
        blocks = extract_code_blocks(response)
        for lang, code in blocks:
            if lang in ("json", ""):
                json_text = code
                break
        if not json_text:
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                json_text = match.group(0)
        if not json_text:
            console.print("[red] Could not find JSON array in response.[/red]")
            return
        try:
            files = json.loads(json_text)
        except json.JSONDecodeError as e:
            console.print(f"[red] Invalid JSON: {e}[/red]")
            return
        if not isinstance(files, list) or not files:
            console.print("[red] Model did not return a valid list of files.[/red]")
            return
        console.print(f"[bold] Creating {len(files)} files...[/bold]")
        for item in files:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            content = item.get("content")
            if path and content is not None:
                result = self.client.tools.write_file(path, content)
                console.print(f"[bold green] {result}[/bold green]")
        console.print("[bold green] Project created.[/bold green]")

    def _list_models(self):
        try:
            r = httpx.get(f"{BASE_URL}/api/models", timeout=30)
            if r.status_code != 200:
                console.print(f"[red] Failed to fetch models: {r.status_code}[/red]")
                return
            data = r.json()
            console.print("[bold] Available models from API:[/bold]")
            for item in data.get("data", []):
                console.print(f" • {item.get('id', 'unknown')} — {item.get('name', 'unnamed')} ({item.get('provider', 'unknown')})")
        except Exception as e:
            console.print(f"[red] Error fetching models: {e}[/red]")

    def _offer_save_code(self, answer: str):
        blocks = extract_code_blocks(answer)
        if not blocks:
            return
        if not self.auto_save:
            console.print(f"[dim] Found {len(blocks)} code block(s).[/dim]")
            for i, (lang, code) in enumerate(blocks, 1):
                if len(blocks) == 1:
                    filename = self.session.prompt(f"Save block {i} as (empty to skip): ")
                else:
                    filename = self.session.prompt(f"Save block {i} ({lang or 'no lang'}) as (empty to skip): ")
                if filename.strip():
                    result = self.client.tools.write_file(filename.strip(), code)
                    console.print(f"[bold green] {result}[/bold green]")
            return

        saved = []
        used_names = set()
        skipped = 0
        for i, (lang, code) in enumerate(blocks, 1):
            filename = _extract_filename_from_block(lang, code)
            if not filename:
                ext = LANG_TO_EXT.get((lang or "").lower(), ".txt")
                filename = f"snippet_{i}{ext}"
            base = filename
            suffix = 2
            while filename in used_names:
                stem, dot, ext = base.rpartition(".")
                filename = f"{stem}-{suffix}.{ext}" if dot else f"{base}-{suffix}"
                suffix += 1
            used_names.add(filename)
            result = self.client.tools.write_file(filename, code)
            if result.startswith("[ok]"):
                saved.append(filename)
            else:
                skipped += 1
                _safe_print(f"[red]{result}[/red]")
        if saved:
            _safe_print(f"[bold green] Auto-saved {len(saved)} file(s):[/bold green] {', '.join(saved)}")
        if skipped:
            _safe_print(f"[yellow]{skipped} block(s) skipped due to errors.[/yellow]")

    def _looks_like_project_request(self, text: str) -> bool:
        t = text.lower()
        hard = [
            "создай проект", "сделай проект", "новый проект",
            "create project", "make project", "build project", "new project",
        ]
        if any(item in t for item in hard):
            return True
        verbs = {"создай", "сделай", "напиши", "собери", "разработай", "create", "build", "make", "write"}
        nouns = {
            "приложение", "игру", "игра", "сайт", "программу", "бота", "скрипт",
            "сервис", "сервер", "app", "application", "game", "site", "website",
            "tool", "script", "bot", "api", "service", "server",
        }
        words = set(re.findall(r"[\w]+", t))
        return bool(words & verbs and words & nouns)

    def _extract_project_description(self, text: str) -> str:
        t = text
        for prefix in ["создай проект", "сделай проект", "новый проект", "create project", "make project", "build project", "new project"]:
            if prefix.lower() in t.lower():
                idx = t.lower().find(prefix.lower())
                t = t[:idx] + t[idx + len(prefix):]
        return t.strip(" \t\"'")

    def _extract_filename_from_request(self, text: str) -> Optional[str]:
        t = text.lower()
        patterns = [
            r"(?:создай|напиши|сделай)\s+(?:файл|файлик)?\s+(\S+)",
            r"(?:create|write)\s+(?:file)?\s+(\S+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, t)
            if match:
                filename = match.group(1).strip('"')
                if filename and not filename.endswith((".", ":", "?", "!")):
                    return filename
        return None

    def _auto_create_file(self, path: str, user_text: str):
        console.print(f"[dim] Auto-creating file: {path}[/dim]")
        with console.status(f"[bold {self.theme.accent}] Generating...[/bold {self.theme.accent}]"):
            answer = self.client.chat(user_text)
        if not answer:
            console.print("[red] Model returned empty response.[/red]")
            return
        cleaned = answer.strip()
        if cleaned.startswith("<tool>"):
            cleaned = re.sub(r"^<tool>\s*", "", cleaned)
            cleaned = re.sub(r"\s*</tool>\s*$", "", cleaned)
        result = self.client.tools.write_file(path, cleaned)
        console.print(f"[bold green] {result}[/bold green]")


def main():
    parser = argparse.ArgumentParser(description="Unlimited Code — console AI coding agent")
    parser.add_argument("folder", nargs="?", default=".", help="Project folder")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model ID or alias")
    args = parser.parse_args()
    project_folder = Path(args.folder).expanduser().resolve()
    if not project_folder.exists():
        console.print(f"[red] Folder not found: {project_folder}[/red]")
        sys.exit(1)
    model = AVAILABLE_MODELS.get(args.model, args.model)
    try:
        app = UnlimitedCodeApp(project_folder, model)
        app.run()
    except Exception as e:
        import traceback
        console.print(f"\n[bold red] Fatal error:[/bold red] {e}")
        log_path = Path.cwd() / "unlimited_code_crash.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Fatal error: {e}\n\n")
            traceback.print_exc(file=f)
        console.print(f"[yellow] Crash log saved to: {log_path}[/yellow]")
        sys.exit(1)


if __name__ == "__main__":
    main()
