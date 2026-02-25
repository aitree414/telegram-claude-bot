import base64

import anthropic

from .memory import ConversationMemory
from .project_loader import get_system_prompt
from .tools import TOOL_DEFINITIONS, execute_tool

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
MAX_TOOL_ITERATIONS = 15
TOOL_RESULT_MAX_LEN = 3000  # Truncate large tool results to avoid context overflow
SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


class ClaudeClient:
    def __init__(self, api_key: str, authorized_user_id: int = 0):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._memory = ConversationMemory()
        self._system = get_system_prompt()
        self._authorized_user_id = authorized_user_id

    def _agentic_loop(self, messages: list, authorized: bool = False) -> str:
        """Run agentic loop with tool use. Returns final text reply."""
        working_messages = list(messages)

        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=self._system,
                tools=TOOL_DEFINITIONS,
                messages=working_messages,
            )

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text_blocks = [b for b in response.content if b.type == "text"]
                return text_blocks[0].text if text_blocks else ""

            working_messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for t in tool_uses:
                result = execute_tool(t.name, t.input, authorized=authorized)
                if len(result) > TOOL_RESULT_MAX_LEN:
                    result = result[:TOOL_RESULT_MAX_LEN] + "\n...(輸出已截斷)"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": t.id,
                    "content": result,
                })
            working_messages.append({"role": "user", "content": tool_results})

        # Final call without tools after max iterations
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self._system,
            messages=working_messages,
        )
        text_blocks = [b for b in response.content if b.type == "text"]
        return text_blocks[0].text if text_blocks else "任務已執行完畢。"

    def chat(self, user_id: int, text: str) -> str:
        authorized = (user_id == self._authorized_user_id)
        self._memory.add_message(user_id, "user", text)
        reply = self._agentic_loop(self._memory.get_history(user_id), authorized=authorized)
        self._memory.add_message(user_id, "assistant", reply)
        return reply

    def analyze_image(
        self, user_id: int, image_data: bytes, media_type: str, caption: str = ""
    ) -> str:
        image_b64 = base64.standard_b64encode(image_data).decode("utf-8")
        content: list = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": image_b64},
            },
            {"type": "text", "text": caption if caption else "請分析這張圖片。"},
        ]
        self._memory.add_message(user_id, "user", content)
        reply = self._agentic_loop(self._memory.get_history(user_id))
        self._memory.add_message(user_id, "assistant", reply)
        return reply

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
        pdf_b64 = base64.standard_b64encode(pdf_data).decode("utf-8")
        content: list = [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
            },
            {"type": "text", "text": caption if caption else "請分析這份 PDF 文件。"},
        ]
        self._memory.add_message(user_id, "user", content)
        reply = self._agentic_loop(self._memory.get_history(user_id))
        self._memory.add_message(user_id, "assistant", reply)
        return reply

    def clear_memory(self, user_id: int) -> None:
        self._memory.clear(user_id)
