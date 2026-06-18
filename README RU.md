# Unlimited Code RU

![Logo](assets/logo.png)

Unlimited Code - консольный AI-агент для работы с локальными проектами. Он умеет смотреть структуру папки, читать и создавать файлы, запускать shell-команды, сохранять историю чатов и работать через API Unlimited AI.

## Возможности

- Консольный REPL-интерфейс.
- Выбор рабочей папки проекта через `/folder` или `/pick`.
- Переключение моделей через `/model`.
- Темы оформления через `/theme`, включая попытку сменить реальный фон терминала.
- Работа с файлами: чтение, запись, список дерева, поиск.
- Создание одного файла через `/create` или целого проекта через `/project`.
- Авто-сохранение code blocks из ответа модели через `/autosave`.
- История чатов через `/chats` и авто-resume последнего чата.
- Streaming-ответы от Unlimited AI.

## Установка

```bash
cd unlimited_code
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows:

```bat
cd unlimited_code
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

Также можно установить проект через `pyproject.toml`:

```bash
pip install -e .
```

## Настройка API

Скопируйте пример окружения и впишите свой ключ:

```bash
cp .env.example .env
```

В `.env` должно быть примерно так:

```env
UNLIMITED_API_KEY=ua_your_real_key_here
UNLIMITED_BASE_URL=https://unlimited.surf
```

Не храните реальный ключ в README, исходниках, `run.bat`, `run.sh` или публичных логах. `.env` уже добавлен в `.gitignore`.

## Запуск

Текущая папка как проект:

```bash
python unlimited_code.py
```

Конкретная папка проекта:

```bash
python unlimited_code.py /path/to/project
```

Готовые скрипты:

```bash
./run.sh /path/to/project
run.bat C:\path\to\project
```

## Команды

- `/help` - показать список команд.
- `/model [name]` - выбрать модель.
- `/models` - показать модели из API.
- `/theme [name]` - выбрать тему: `dark`, `hacker`, `neon`, `ocean`, `sunset`.
- `/folder <path>` - сменить рабочую папку.
- `/pick` - открыть GUI-выбор папки, если доступен.
- `/files [path] [depth]` - показать дерево файлов.
- `/create <path> <description>` - создать файл через AI.
- `/edit <path> <description>` - отредактировать файл через AI.
- `/project <description>` - создать несколько файлов как проект.
- `/mkdir <path>` - создать папку.
- `/default-lang <language>` - задать язык по умолчанию для генерации.
- `/speed <low|medium|high>` - настроить effort/speed.
- `/instructions <text>` - добавить инструкции к системному промпту.
- `/debug` - включить или выключить вывод raw payload.
- `/autosave [on|off]` - авто-сохранение code blocks. По умолчанию включено.
- `/chats` или `/chathistory` - список сохраненных чатов.
- `/chats save [name]` - сохранить текущий чат.
- `/chats switch <id-or-name-part>` - переключиться на чат.
- `/chats rename <name>` - переименовать текущий чат.
- `/chats delete <id-or-part>` - удалить чат.
- `/chats new` или `/newchat` - начать новый чат.
- `/reset` - сбросить текущую историю.
- `exit` или `quit` - выйти.

## История Чатов

Чаты сохраняются в папке проекта:

```text
.unlimited_code/chats/
```

При запуске Unlimited Code пытается автоматически открыть последний чат. История также вставляется прямо в запрос к модели, потому что endpoint `/api/chat` может не учитывать отдельное поле `history`.

## Автосохранение Кода

Когда модель возвращает markdown code block, Unlimited Code по умолчанию сохраняет его в файл автоматически.

Чтобы подсказать имя файла, модель может написать в начале блока:

```python
# file: src/main.py
print("hello")
```

Если имя не найдено, файл будет сохранен как `snippet_1.py`, `snippet_2.js` и так далее по языку блока.

Отключить старое поведение можно так:

```text
/autosave off
```

## Темы

Доступные темы:

| Тема | Фон | Превью |
|---|---|---|
| `dark` | `#0d1117` | ![](docs/preview_dark.png) |
| `hacker` | `#0a140a` | ![](docs/preview_hacker.png) |
| `neon` | `#1a0033` | ![](docs/preview_neon.png) |
| `ocean` | `#001f3f` | ![](docs/preview_ocean.png) |
| `sunset` | `#2a0a0a` | ![](docs/preview_sunset.png) |

Фон терминала меняется через OSC escape. Это поддерживают Windows Terminal, iTerm2, kitty, foot и часть современных Linux-терминалов. Если терминал не поддерживает OSC, приложение продолжит работать без смены реального фона.

## Безопасность

- `UNLIMITED_API_KEY` читается только из `.env` или переменной окружения.
- В коде и `.env.example` не должно быть настоящего ключа.
- Если ключ когда-либо попал в чат, лог или репозиторий, перевыпустите его.
- `run_command` выполняется внутри выбранной папки проекта.
- Пути файлов ограничены корнем проекта.

## Структура

```text
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
```
