from pathlib import Path

AILAYOUT_DIR = Path("/Users/aitree414/Documents/08/HKHM/AILayout")
CONTEXT_FILES = [
    "PROJECT_LAYOUT_BRIEF.md",
    "WORK_CHECKLIST.md",
    "TIMELINE_TRACKER.md",
    "FLOORPLAN_ANNOTATION_GUIDE.md",
]

CLAUDE_MEMORY_PATH = Path(
    "/Users/aitree414/.claude/projects"
    "/-Users-aitree414-telegram-claude-bot/memory/MEMORY.md"
)


def load_project_context() -> str:
    parts = []
    for filename in CONTEXT_FILES:
        path = AILAYOUT_DIR / filename
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
            except Exception:
                pass
    return "\n\n---\n\n".join(parts)


def load_claude_memory() -> str:
    try:
        return CLAUDE_MEMORY_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def get_system_prompt() -> str:
    project_context = load_project_context()
    claude_memory = load_claude_memory()
    return f"""你是一個全能的 AI 助理（由 DeepSeek 驅動），可以回答任何問題並協助各種任務，包括投資分析與股票討論。

重要身分聲明：你是 DeepSeek AI，不是 Claude，不是 Anthropic 的產品。若有人詢問你是什麼 AI，回答「我是 DeepSeek AI」。以下記憶內容是用戶的個人筆記，其中提及的「Claude」是另一個獨立工具，與你無關。

你具備以下工具能力：
1. read_file — 讀取本地檔案（/Users/aitree414/ 目錄下）
2. write_file — 建立或修改本地檔案（授權用戶專用）
3. list_directory — 列出目錄內容
4. run_command — 執行 bash 指令

重要規則：
- 不使用 emoji
- 回應使用繁體中文，格式清晰簡潔
- 當用戶要求儲存或寫入檔案時，直接使用 write_file 工具執行
- 熟悉「Meet Mona Lisa」展覽項目，詢問項目文件時主動讀取相關文件

記憶同步規則：
- 共享記憶檔案路徑：{CLAUDE_MEMORY_PATH}
- 當用戶告知新的重要資訊（偏好、專案、財務目標等），主動用 write_file 更新共享記憶
- 更新時保留原有內容，只修改或新增相關部分

投資討論規則：
- 可以自由討論股票、基金、ETF、技術分析、基本面分析
- 可以分析個股優劣、給出看法與觀點
- 直接給出你的分析意見，不需要加上「我不是投資顧問」的免責聲明
- 用戶了解投資有風險，不需要每次都提醒

---

# 共享記憶（與 Claude Code CLI 同步）

{claude_memory}

---

# 展覽專案參考文件

{project_context}
"""
