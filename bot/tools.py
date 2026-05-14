import json
import subprocess
from pathlib import Path
from typing import Optional

import httpx

ALLOWED_ROOT = Path("/Users/aitree414")
ALLOWED_COMMANDS = frozenset({
    "ls", "find", "grep", "cat", "head", "tail", "wc", "file", "du", "pwd", "echo"
})

# Blocked dangerous commands regardless of authorization
BLOCKED_COMMANDS = frozenset({
    "rm", "rmdir", "mkfs", "dd", "shutdown", "reboot", "halt", "poweroff",
    "sudo", "su", "chmod", "chown", "kill", "killall", "mv", "cp", "scp",
    "curl", "wget", "nc", "netcat", "telnet", "ssh", "python", "python3",
    "node", "npm", "pip", "bash", "zsh", "sh", "csh", "ksh", "perl", "php",
    "ruby", "java", "go", "rustc", "gcc", "g++", "clang", "make", "cmake",
    "git", "svn", "hg", "tar", "zip", "unzip", "gzip", "bzip2", "xz",
    "openssl", "ssh-keygen", "ssh-copy-id", "rsync", "ftp", "sftp", "lftp",
    "mount", "umount", "fdisk", "parted", "mkfs.ext4", "mkfs.ntfs",
    "useradd", "userdel", "usermod", "groupadd", "groupdel", "groupmod",
    "passwd", "visudo", "crontab", "at", "batch", "service", "systemctl",
    "iptables", "ufw", "firewall-cmd", "nft", "ip", "ifconfig", "route",
    "arp", "netstat", "ss", "tcpdump", "wireshark", "nmap", "masscan",
    "hydra", "metasploit", "aircrack-ng", "john", "hashcat", "sqlmap",
    "nikto", "gobuster", "dirb", "wpscan", "nuclei", "zap", "burpsuite",
    "ettercap", "dsniff", "etterlog", "etterfilter", "ettercap-ng",
    "dsniff", "filesnarf", "mailsnarf", "msgsnarf", "urlsnarf", "webspy",
    "sshmitm", "webmitm", "dnsspoof", "macof", "tcpkill", "tcpnice",
    "tcpreplay", "tcptrace", "tcptraceroute", "traceroute", "tracepath",
    "mtr", "ping", "ping6", "fping", "hping3", "nping", "thc-ssl-dos",
})

# Dangerous shell patterns that could lead to command injection
DANGEROUS_PATTERNS = frozenset({
    "$(", "`",  # command substitution
    ";", "&&", "||", "&", "|",  # command separators and pipes
    ">", ">>", "<", "<<",  # redirections
    "\\", "\n", "\r",  # line continuations and newlines
})

# Extremely dangerous patterns that should be blocked even for authorized users
EXTREME_DANGEROUS_PATTERNS = frozenset({
    "$(", "`",  # command substitution
    "\\", "\n", "\r",  # line continuations and newlines
})

def _sanitize_command(command: str, authorized: bool = False) -> tuple[bool, str]:
    """
    Check if command is safe to execute.
    Returns (is_safe, error_message).
    """
    command = command.strip()
    if not command:
        return False, "空指令"

    # Extract base command (first word)
    parts = command.split()
    if not parts:
        return False, "無效指令"

    base_cmd = parts[0]

    # Check blocked commands
    if base_cmd in BLOCKED_COMMANDS:
        return False, f"危險指令 '{base_cmd}' 已封鎖。"

    # Check extreme dangerous patterns for all users
    for pattern in EXTREME_DANGEROUS_PATTERNS:
        if pattern in command:
            return False, f"指令包含危險模式 '{pattern}'，已拒絕。"

    # For non-authorized users, only allow simple commands without shell features
    if not authorized:
        if base_cmd not in ALLOWED_COMMANDS:
            return False, f"無權執行 '{base_cmd}'。"

        # Check for all dangerous patterns for non-authorized users
        for pattern in DANGEROUS_PATTERNS:
            if pattern in command:
                return False, f"指令包含危險模式 '{pattern}'，已拒絕。"

    return True, ""


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
    p = Path(path)
    if not p.exists():
        return f"找不到檔案：{path}"
    try:
        # Handle different file types
        suffix = p.suffix.lower()

        # PDF files — extract text with pypdf + OCR fallback
        if suffix == ".pdf":
            try:
                import io, pypdf
                reader = pypdf.PdfReader(io.BytesIO(p.read_bytes()))
                pages = [page.extract_text() or "" for page in reader.pages]
                text = "\n\n".join(pages)
                if text.strip():
                    total = len(reader.pages)
                    return text[:8000] + (f"\n\n...（共 {total} 頁，顯示前 8000 字元）" if len(text) > 8000 else "")
                # OCR fallback for scanned PDFs
                try:
                    from pdf2image import convert_from_bytes
                    import pytesseract
                    images = convert_from_bytes(p.read_bytes(), dpi=300)
                    ocr = [f"--- 第 {i+1} 頁 ---\n{pytesseract.image_to_string(img, lang='eng+chi_tra').strip()}" for i, img in enumerate(images)]
                    return "\n\n".join(ocr)[:8000]
                except ImportError:
                    return "此 PDF 無文字層（掃描檔），需安裝 pdf2image+pytesseract 才能 OCR。"
            except ImportError:
                return "需安裝 pypdf 才能讀取 PDF：pip install pypdf"
            except Exception as e:
                return f"PDF 讀取失敗：{e}"

        # JSON — pretty-print
        if suffix in (".json", ".jsonl"):
            try:
                data = json.loads(p.read_text("utf-8"))
                return json.dumps(data, ensure_ascii=False, indent=2)[:8000]
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # fall through to raw text

        # CSV / TSV
        if suffix in (".csv", ".tsv"):
            import csv, io
            try:
                dialect = "excel-tab" if suffix == ".tsv" else "excel"
                rows = list(csv.reader(io.StringIO(p.read_text("utf-8")), dialect=dialect))
                if rows:
                    col_widths = [max(len(str(r[i])) for r in rows if i < len(r)) for i in range(len(rows[0]))] if rows else []
                    lines = ["  ".join(f"{str(r[i]):{col_widths[i]}s}" if i < len(col_widths) else str(r[i]) for i in range(len(r))) for r in rows]
                    return "\n".join(lines[:200]) + (f"\n\n...（共 {len(rows)} 行）" if len(rows) > 200 else "")
            except Exception:
                pass  # fall through

        # Try UTF-8 text
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Binary file — return file info instead of garbled content
        try:
            size = p.stat().st_size
            return f"[二進位檔案] {p.name} ({size:,} bytes)\n此檔案非純文字格式。如需分析，請直接上傳檔案。"
        except Exception:
            return f"[二進位檔案] 無法讀取爲文字。"
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
    # Sanitize command first
    is_safe, error = _sanitize_command(command, authorized)
    if not is_safe:
        return error

    try:
        # For non-authorized users, use shell=False to prevent injection
        # But we need to handle simple commands with arguments
        if not authorized:
            # Simple command splitting without shell features
            import shlex
            args = shlex.split(command)
            result = subprocess.run(
                args, shell=False, capture_output=True, text=True, timeout=30
            )
        else:
            # Authorized users can use shell features but with sanitization
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )

        output = result.stdout or result.stderr
        return output[:4000] if output else "（無輸出）"
    except subprocess.TimeoutExpired:
        return "錯誤：指令執行逾時"
    except Exception as e:
        return f"執行錯誤：{e}"


def fetch_webpage(url: str, max_length: int = 8000, cookies: str = "") -> str:
    """Fetch and extract text content from a URL.

    Automatically uses stored cookies for the domain (see ``/cookies`` command).
    Also accepts an optional inline cookie string for one-time use.

    Parameters
    ----------
    url : str
        The URL to fetch (must be http/https).
    max_length : int
        Max characters to return (default 8000).
    cookies : str
        Optional. Inline cookies in ``name=value; name2=value2`` format.
        These are merged on top of any stored cookies for the domain.

    Returns
    -------
    str — page text content or error message.
    """
    if not url.startswith(("http://", "https://")):
        return "錯誤：只支援 http/https URL。"
    try:
        # Auto-load stored cookies for this domain
        from urllib.parse import urlparse
        from .cookie_store import get_cookies
        domain = urlparse(url).hostname or ""
        cookie_dict = get_cookies(domain)
        # Merge inline cookies on top
        if cookies:
            for pair in cookies.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    cookie_dict[k.strip()] = v.strip()

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        }
        resp = httpx.get(
            url, timeout=15, follow_redirects=True,
            headers=headers, cookies=cookie_dict or None,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type or "application/json" in content_type:
            text = resp.text
        else:
            text = resp.content.decode("utf-8", errors="replace")
        # Basic HTML tag stripping for readability
        import re
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_length:
            text = text[:max_length] + f"\n...(截斷，全文 {len(text)} 字元)"
        return text or "（頁面無文字內容）"
    except httpx.TimeoutException:
        return "錯誤：連線逾時"
    except httpx.HTTPStatusError as e:
        return f"錯誤：HTTP {e.response.status_code}"
    except Exception as e:
        return f"錯誤：{e}"


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
    if name == "fetch_webpage":
        return fetch_webpage(
            inputs["url"],
            inputs.get("max_length", 8000),
            inputs.get("cookies", ""),
        )
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
            "name": "fetch_webpage",
            "description": "取得公開網頁的文字內容。回傳純文字（已移除 HTML 標籤），最多 8000 字元。自動使用該網域已儲存的 cookies（可用 /cookies 指令管理）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要讀取的網址（http/https）"},
                    "max_length": {"type": "integer", "description": "回傳最大字元數，預設 8000"},
                    "cookies": {"type": "string", "description": "選用。臨時 cookies，格式 name=value; name2=value2。會與已儲存的 cookies 合併。"},
                },
                "required": ["url"],
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
        "name": "fetch_webpage",
        "description": "取得公開網頁的文字內容。回傳純文字（已移除 HTML 標籤），最多 8000 字元。自動使用該網域已儲存的 cookies。",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要讀取的網址（http/https）"},
                "max_length": {"type": "integer", "description": "回傳最大字元數，預設 8000"},
                "cookies": {"type": "string", "description": "選用。臨時 cookies，格式 name=value; name2=value2。"},
            },
            "required": ["url"],
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
