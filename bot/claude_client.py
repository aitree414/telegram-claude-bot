import base64
import json
import logging

import openai

from .memory import ConversationMemory
from .project_loader import get_system_prompt
from .tools import OPENAI_TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

MODEL = "deepseek-chat"
MAX_TOKENS = 4096
MAX_TOOL_ITERATIONS = 8
TOOL_RESULT_MAX_LEN = 2000
SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


class ClaudeClient:
    def __init__(self, api_key: str, authorized_user_id: int = 0):
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )
        self._memory = ConversationMemory()
        self._authorized_user_id = authorized_user_id

    def _sanitize_messages(self, messages: list) -> list:
        """Convert Anthropic-format content blocks to plain text for DeepSeek."""
        sanitized = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") in ("image", "document"):
                            text_parts.append("[此訊息包含圖片/文件，DeepSeek 不支援，已略過]")
                    elif isinstance(block, str):
                        text_parts.append(block)
                if text_parts:
                    sanitized.append({**msg, "content": "\n".join(text_parts)})
            else:
                sanitized.append(msg)
        return sanitized

    def _agentic_loop(self, messages: list, authorized: bool = False) -> str:
        system = get_system_prompt()
        clean_messages = self._sanitize_messages(messages)
        working_messages = [{"role": "system", "content": system}] + clean_messages

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = self._client.chat.completions.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    tools=OPENAI_TOOL_DEFINITIONS,
                    messages=working_messages,
                )
            except Exception as e:
                logger.error(f"DeepSeek API call failed (iteration {iteration}): {e}")
                return f"AI 服務暫時無法回應，請稍後再試。錯誤：{e}"

            message = response.choices[0].message
            tool_calls = message.tool_calls

            if not tool_calls:
                return message.content or ""

            # DeepSeek may return None for message.content when tool_calls are present.
            # OpenAI format requires content to be a string in subsequent messages.
            # Replace None with empty string to prevent API format errors.
            assistant_content = message.content if message.content is not None else ""

            working_messages.append({
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                try:
                    inputs = json.loads(tc.function.arguments)
                    result = execute_tool(tc.function.name, inputs, authorized=authorized)
                except Exception as e:
                    logger.error(f"Tool {tc.function.name} execution failed: {e}")
                    result = f"工具執行錯誤：{e}"

                if len(result) > TOOL_RESULT_MAX_LEN:
                    result = result[:TOOL_RESULT_MAX_LEN] + "\n...(輸出已截斷)"

                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        try:
            response = self._client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=working_messages,
            )
            return response.choices[0].message.content or "任務已執行完畢。"
        except Exception as e:
            logger.error(f"Final API call failed: {e}")
            return "任務已執行，但無法生成最終回覆。"

    def chat(self, user_id: int, text: str) -> str:
        authorized = (user_id == self._authorized_user_id)
        self._memory.add_message(user_id, "user", text)
        reply = self._agentic_loop(self._memory.get_history(user_id), authorized=authorized)
        self._memory.add_message(user_id, "assistant", reply)
        return reply

    def analyze_image(
        self, user_id: int, image_data: bytes, media_type: str, caption: str = ""
    ) -> str:
        text = caption if caption else "收到一張圖片，但目前模型不支援圖片分析，請用文字描述圖片內容。"
        return self.chat(user_id, text)

    def analyze_file(
        self, user_id: int, file_data: bytes, filename: str, caption: str = ""
    ) -> str:
        if filename.lower().endswith(".pdf"):
            return self._analyze_pdf(user_id, file_data, caption)
        try:
            text_content = file_data.decode("utf-8")
        except UnicodeDecodeError:
            text_content = file_data.decode("latin-1")
        user_message = f"檔案名稱：{filename}\n\n檔案內容：\n{text_content}"
        if caption:
            user_message = f"{caption}\n\n{user_message}"
        return self.chat(user_id, user_message)

    def _analyze_pdf(self, user_id: int, pdf_data: bytes, caption: str = "") -> str:
        try:
            import io
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(pdf_data))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            text_content = "\n\n".join(pages_text)
            if not text_content.strip():
                return "無法從 PDF 提取文字（可能是掃描圖片格式）。"
        except ImportError:
            return "PDF 解析需要安裝 pypdf：pip install pypdf"
        except Exception as e:
            return f"PDF 解析失敗：{e}"
        user_message = f"PDF 文件內容：\n\n{text_content[:8000]}"
        if caption:
            user_message = f"{caption}\n\n{user_message}"
        return self.chat(user_id, user_message)

    def clear_memory(self, user_id: int) -> None:
        self._memory.clear(user_id)
