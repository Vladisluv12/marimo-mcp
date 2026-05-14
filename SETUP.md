# Настройка marimo-mcp

Пошаговая инструкция для подключения marimo-mcp к Claude Code в VS Code на Linux.

---

## Требования

- Linux (Ubuntu / Arch / другой)
- VS Code с расширением [marimo](https://marketplace.visualstudio.com/items?itemName=marimo-team.vscode-marimo)
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Node.js 18+ — для сборки bridge extension
- Claude Code (CLI или VS Code extension)

---

## Шаг 1: Клонировать и собрать

```bash
git clone https://github.com/Vladisluv12/marimo-mcp.git ~/marimo-mcp
cd ~/marimo-mcp
uv sync                # создаёт .venv и ставит зависимости
```

Проверить:
```bash
uv run marimo-mcp --help   # должен вывести справку FastMCP
```

---

## Шаг 2: Собрать и установить bridge extension

Bridge — это VS Code расширение, которое запускает HTTP сервер внутри VS Code и позволяет Claude работать с ноутбуками без запуска `marimo edit`.

```bash
cd ~/marimo-mcp/marimo-mcp-bridge
npm install
bash install.sh
```

`install.sh` делает три вещи: компилирует TypeScript → упаковывает VSIX → устанавливает в VS Code.

После установки:
- **Ctrl+Shift+P** → **Developer: Reload Window**

Проверить что bridge запустился:
```bash
curl http://127.0.0.1:42018/health
# {"status":"ok"}
```

> **Несколько окон VS Code:** bridge автоматически занимает порты 42018–42027 (по одному на окно). Claude видит ноутбуки из всех окон одновременно.

---

## Шаг 3: Настроить Python окружение

Bridge автоматически ищет Python в следующем порядке:
1. `.venv/bin/python` рядом с файлом ноутбука
2. `.venv/bin/python` в корне workspace
3. Активный interpreter из VS Code Python extension
4. `python3` (системный fallback)

Для правильной работы создай `.venv` с marimo в корне своего проекта:

```bash
cd ~/my-project
python3 -m venv .venv
.venv/bin/pip install marimo
```

Затем в VS Code выбери этот interpreter:
- **Ctrl+Shift+P** → **Python: Select Interpreter** → выбери `.venv/bin/python` из своего проекта

---

## Шаг 4: Подключить MCP сервер к Claude Code

### Вариант А: глобально для всех проектов

Добавь в `~/.claude/mcp.json` (создай если нет):

```json
{
  "mcpServers": {
    "marimo": {
      "command": "uv",
      "args": ["run", "marimo-mcp"],
      "cwd": "/home/<твой_юзер>/marimo-mcp"
    }
  }
}
```

### Вариант Б: только для конкретного проекта

Добавь в `.vscode/mcp.json` в корне проекта:

```json
{
  "mcpServers": {
    "marimo": {
      "command": "uv",
      "args": ["run", "marimo-mcp"],
      "cwd": "/home/<твой_юзер>/marimo-mcp"
    }
  }
}
```

### Если marimo требует токен аутентификации

По умолчанию marimo генерирует случайный токен. Либо:
- Запускай с `--no-token` чтобы отключить, **или**
- Добавь токен из URL запуска (`?access_token=...`) в конфигурацию:

```json
{
  "mcpServers": {
    "marimo": {
      "command": "uv",
      "args": ["run", "marimo-mcp"],
      "cwd": "/home/<твой_юзер>/marimo-mcp",
      "env": {
        "MARIMO_TOKEN": "вставь-токен-сюда"
      }
    }
  }
}
```

---

## Шаг 5: Проверить установку

1. Открой любой `.py` marimo ноутбук в VS Code
2. Запусти Claude Code в том же окне
3. Попроси Claude:

```
list_notebooks
```

Должен вернуть список с твоим ноутбуком и `"via": "vscode"`.

Полная проверка:
```
get_cells notebook.py     → список ячеек с cell_id
edit_and_run_cell notebook.py <cell_id> "print('hello')"   → {"output": "hello"}
```

---

## Шаг 6: Установить skill для Claude Code (опционально)

Skill автоматически настраивает Claude на правильную работу с marimo-mcp. Уже включён если `marimo-mcp@marimo-mcp` есть в `~/.claude/settings.json` в разделе `enabledPlugins`.

Проверить:
```bash
grep "marimo-mcp" ~/.claude/settings.json
```

Если нет — добавить вручную:
```json
{
  "enabledPlugins": {
    "marimo-mcp@marimo-mcp": true
  }
}
```

---

## Обновление bridge после изменений

Если обновил код bridge extension:

```bash
cd ~/marimo-mcp/marimo-mcp-bridge
bash install.sh
# затем в VS Code: Developer: Reload Window
```

---

## Диагностика

### Bridge не отвечает

```bash
curl http://127.0.0.1:42018/health
```

- Нет ответа → расширение не запустилось. Проверь **VS Code Output** → вкладка **marimo-mcp-bridge**
- `EADDRINUSE` → порт занят другим процессом (не нашим bridge). Перезагрузи VS Code.

### Ноутбук не виден в `list_notebooks`

```bash
curl http://127.0.0.1:42018/notebooks
```

- Пустой список → ноутбук не открыт как marimo notebook. Открой `.py` файл в VS Code — marimo extension должна его подхватить (иконка в заголовке вкладки)
- Видно ноутбук, но Claude не находит → проверь что MCP сервер запущен (`cwd` в конфиге указывает на папку marimo-mcp)

### Неправильный Python в ячейках

```bash
curl http://127.0.0.1:42018/debug
```

Поле `executable` показывает какой Python будет использоваться. Если это не `.venv` твоего проекта:
1. Убедись что `.venv/bin/python` существует в workspace
2. Выбери interpreter: **Ctrl+Shift+P** → **Python: Select Interpreter**
3. Перезагрузи окно VS Code

### `edit_and_run_cell` timeout (15 секунд)

- Ноутбук должен быть **видим** в VS Code (не свёрнут)
- Попробуй запустить любую ячейку вручную — это разогревает kernel
- Проверь **VS Code Output** → **marimo** на ошибки kernel

### После `add_cell` не работает `edit_and_run_cell` на новой ячейке

Это известное ограничение: после `add_cell` нужно вызвать `get_cells` снова чтобы получить актуальный `cell_id` который присвоил marimo.

```
add_cell → get_cells → edit_and_run_cell с новым cell_id
```
