import base64
import json

import openai

from .memory import ConversationMemory
from .project_loader import get_system_prompt
from .tools import OPENAI_TOOL_DEFINITIONS, execute_tool

MODEL = "deepseek-chat"
MAX_TOKENS = 2048
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

    def _agentic_loop(self, messages: list, authorized: bool = False) -> str:
        system = get_system_prompt()
        working_messages = [{"role": "system", "content": system}] + list(messages)

        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                tools=OPENAI_TOOL_DEFINITIONS,
                messages=working_messages,
            )

            message = response.choices[0].message
            tool_calls = message.tool_calls

            if not tool_calls:
                return message.content or ""

            working_messages.append({
                "role": "assistant",
                "content": message.content,
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
                inputs = json.loads(tc.function.arguments)
                result = execute_tool(tc.function.name, inputs, authorized=authorized)
                if len(result) > TOOL_RESULT_MAX_LEN:
                    result = result[:TOOL_RESULT_MAX_LEN] + "\n...(輸出已截斷)"
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        response = self._client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=working_messages,
        )
        return response.choices[0].message.content or "任務已執行完畢。"

    def chat(self, user_id: int, text: str) -> str:
        authorized = (user_id == self._authorized_user_id)
        self._memory.add_message(user_id, "user", text)
        reply = self._agentic_loop(self._memory.get_history(user_id), authorized=authorized)
        self._memory.add_message(user_id, "assistant", reply)
        return reply

    def analyze_image(
        self, user_id: int, image_data: bytes, media_type: str, caption: str = ""
    ) -> str:
        # DeepSeek-chat 不支援圖片，以文字方式回應
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
