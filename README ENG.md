# Unlimited Code ENG

![Logo](assets/logo.png)



to use this CLI just 




Unlimited Code is a console AI agent for working with local projects. It can inspect a folder structure, read and create files, run shell commands, save chat history, and work through the Unlimited AI API.

Features

Console REPL interface.
Choose the project's working folder via /folder or /pick.
Switch models via /model.
Themes via /theme, including attempts to change the terminal's actual background.
File operations: read, write, tree listing, search.
Create a single file via /create or an entire project via /project.
Auto-save code blocks from the model's response via /autosave.
Chat history via /chats and auto-resume of the last chat.
Streaming responses from Unlimited AI.

Installation
bash
Copy
cd unlimited_code
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Windows:
bat
Copy
cd unlimited_code
.venv\Scripts\activate.bat
pip install -r requirements.txt

You can also install the project via pyproject.toml:
bash
Copy
pip install -e .

API Setup

Copy the environment example and insert your key:
bash
Copy
cp .env.example .env

Your .env should look roughly like this:
env
Copy
UNLIMITED_API_KEY=ua_your_real_key_here
UNLIMITED_BASE_URL=https://unlimited.surf

Do not store a real key in the README, source code, run.bat, run.sh, or public logs. .env is already included in .gitignore.

##

Run

Current folder as the project:
bash
Copy
python unlimited_code.py

Specific project folder:
bash
Copy
python unlimited_code.py /path/to/project

Ready-made scripts:
bash
Copy
./run.sh /path/to/project
run.bat C:\path\to\project

Commands

/help - show the list of commands.
/model [name] - select a model.
/models - show models from the API.
/theme [name] - choose a theme: dark, hacker, neon, ocean, sunset.
/folder <path> - change the working folder.
/pick - open a GUI folder picker, if available.
/files [path] [depth] - show the file tree.
/create <path> <description> - create a file via AI.
/edit <path> <description> - edit a file via AI.
/project <description> - create multiple files as a project.
/mkdir <path> - create a folder.
/default-lang <language> - set the default language for generation.
/speed <low|medium|high> - configure effort/speed.
/instructions <text> - add instructions to the system prompt.
/debug - enable or disable raw payload output.
/autosave [on|off] - auto-save code blocks. Enabled by default.
/chats or /chathistory - list saved chats.
/chats save [name] - save the current chat.
/chats switch <id-or-name-part> - switch to a chat.
/chats rename <name> - rename the current chat.
/chats delete <id-or-part> - delete a chat.
/chats new or /newchat - start a new chat.
/reset - reset the current history.
exit or quit - exit.

Chat History

Chats are stored in the project folder:
text
Copy
.unlimited_code/chats/

When Unlimited Code starts, it tries to automatically open the last chat. The history is also inserted directly into the request to the model because the /api/chat endpoint may not respect a separate history field.

Code Auto-Save

When the model returns a markdown code block, Unlimited Code saves it to a file automatically by default.

To suggest a filename, the model can write this at the beginning of the block:
python
Copy
# file: src/main.py
print("hello")

If no filename is found, the file will be saved as snippet_1.py, snippet_2.js, and so on based on the block language.

You can disable the old behavior like this:
text
Copy
/autosave off

Themes

Available themes:

| Theme | Background | Preview |
|---|---|---|
| dark | #0d1117 | ![](docs/preview_dark.png) |
| hacker | #0a140a | ![](docs/preview_hacker.png) |
| neon | #1 a0033 | ![](docs/preview_neon.png) |
| ocean | #001f3f | ![](docs/preview_ocean.png) |
| sunset | #2a0a0a | ![](docs/preview_sunset.png) |

The terminal background is changed via OSC escape sequences. This is supported by Windows Terminal, iTerm2, kitty,

foot, and some modern Linux terminals. If the terminal does not support OSC, the application will continue to work without changing the actual background.

Security

UNLIMITED_API_KEY is read only from .env or an environment variable.
There must not be a real key in the code or .env.example.
If the key has ever been exposed in a chat, log, or repository, rotate it.
run_command is executed inside the selected project folder.
File paths are restricted to the project root.

Structure
text
Copy
unlimited_code/
  assets/
    logo.png
  docs/
    preview_dark.png
    preview_hacker.png
    preview_neon.png
    preview_ocean.png
    preview_sunset.png
  unlimited_code.py
  unlimited_code_limited.py
  pyproject.toml
  requirements.txt
  run.sh
  run.bat
  .env.example
  .gitignore
  README.md
``````_hacker.png
    preview_neon.png
    preview_ocean.png
    preview_sunset.png
  unlimited_code.py
  unlimited_code_limited.py
  pyproject.toml
  requirements.txt
  run.sh
  run.bat
  .env.example
  .gitignore
  README.md
