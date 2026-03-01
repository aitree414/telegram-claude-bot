import subprocess
from pathlib import Path
from typing import Optional

ALLOWED_ROOT = Path("/Users/aitree414")
ALLOWED_COMMANDS = frozenset({
    "ls", "find", "grep", "cat", "head", "tail", "wc", "file", "du", "pwd", "echo"
})

# Blocked dangerous commands regardless of authorization
BLOCKED_COMMANDS = frozenset({
    "rm", "rmdir", "mkfs", "dd", "shutdown", "reboot", "halt", "poweroff",
    "sudo", "su", "chmod", "chown", "kill", "killall"
})


def _check_path(path: str) -> Optional[str]:
    """Returns error string if path is not allowed, else None."""
    try:
        resolved = Path(path).resolve()
        if not str(resolved).startswith(str(ALLOWED_ROOT)):
            return f"拒絕存取：只允許 {ALLOWED_ROOT} 目錄下的路徑。"
    except Exception as e:
        return f"路徑無效：{e}"
    return None


def read_file(path: str) -> str:
    err = _check_path(path)
    if err:
        return err
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Path(path).read_bytes().decode("latin-1")
    except FileNotFoundError:
        return f"找不到檔案：{path}"
    except Exception as e:
        return f"讀取錯誤：{e}"


def list_directory(path: str) -> str:
    err = _check_path(path)
    if err:
        return err
    try:
        entries = sorted(Path(path).iterdir())
        lines = [
            f"{'[目錄]' if e.is_dir() else '[檔案]'} {e.name}"
            for e in entries
        ]
        return "\n".join(lines) if lines else "（空目錄）"
    except FileNotFoundError:
        return f"找不到目錄：{path}"
    except Exception as e:
        return f"列出目錄錯誤：{e}"


def run_command(command: str, authorized: bool = False) -> str:
    base_cmd = command.strip().split()[0] if command.strip() else ""
    if base_cmd in BLOCKED_COMMANDS:
        return f"危險指令 '{base_cmd}' 已封鎖。"
    if not authorized and base_cmd not in ALLOWED_COMMANDS:
        return f"無權執行 '{base_cmd}'。"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout or result.stderr
        return output[:4000] if output else "（無輸出）"
    except subprocess.TimeoutExpired:
        return "錯誤：指令執行逾時"
    except Exception as e:
        return f"執行錯誤：{e}"


def write_file(path: str, content: str, authorized: bool = False) -> str:
    if not authorized:
        return "無權寫入檔案，只有授權用戶可以使用此功能。"
    err = _check_path(path)
    if err:
        return err
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"檔案已儲存：{path}"
    except Exception as e:
        return f"寫入錯誤：{e}"


def execute_tool(name: str, inputs: dict, authorized: bool = False) -> str:
    if name == "read_file":
        return read_file(inputs["path"])
    if name == "list_directory":
        return list_directory(inputs["path"])
    if name == "run_command":
        return run_command(inputs["command"], authorized=authorized)
    if name == "write_file":
        return write_file(inputs["path"], inputs["content"], authorized=authorized)
    return f"未知工具：{name}"


OPENAI_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "讀取本地檔案內容，只允許 /Users/aitree414/ 目錄下的路徑。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "絕對檔案路徑"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出目錄內容，只允許 /Users/aitree414/ 目錄下的路徑。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目錄路徑"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "執行安全的 bash 指令（ls, find, grep, cat, head, tail, wc, du, pwd）",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "bash 指令"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "建立或覆蓋本地檔案，只允許授權用戶使用，路徑限 /Users/aitree414/ 下。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "絕對檔案路徑"},
                    "content": {"type": "string", "description": "檔案內容"},
                },
                "required": ["path", "content"],
            },
        },
    },
]

TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "讀取本地檔案內容，只允許 /Users/aitree414/ 目錄下的路徑。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "絕對檔案路徑"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "列出目錄內容，只允許 /Users/aitree414/ 目錄下的路徑。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目錄路徑"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": "執行安全的 bash 指令（ls, find, grep, cat, head, tail, wc, du, pwd）",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "bash 指令"}},
            "required": ["command"],
        },
    },
    {
        "name": "write_file",
        "description": "建立或覆蓋本地檔案，只允許授權用戶使用，路徑限 /Users/aitree414/ 下。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "絕對檔案路徑"},
                "content": {"type": "string", "description": "檔案內容"},
            },
            "required": ["path", "content"],
        },
    },
]
