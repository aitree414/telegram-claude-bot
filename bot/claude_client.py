import base64
import json
import logging
import re
import time
from typing import Tuple

import openai

from .memory import ConversationMemory
from .project_loader import get_system_prompt
from .tools import OPENAI_TOOL_DEFINITIONS, execute_tool
from .session_manager import get_session_manager, TaskType
from .retry import retry, async_retry, retry_with_exponential_backoff
from . import constants

logger = logging.getLogger(__name__)

# API retry settings (kept here for backward compatibility)
MAX_API_RETRIES = constants.MAX_API_RETRIES
INITIAL_RETRY_DELAY = constants.INITIAL_RETRY_DELAY
MAX_RETRY_DELAY = constants.MAX_RETRY_DELAY
RETRY_BACKOFF_FACTOR = constants.RETRY_BACKOFF_FACTOR

# Retryable error types
RETRYABLE_ERRORS = (
    openai.APIConnectionError,  # Network errors
    openai.APITimeoutError,     # Timeout errors
    openai.RateLimitError,      # Rate limiting
    openai.InternalServerError, # 5xx server errors
)


class ClaudeClient:
    def __init__(self, api_key: str, authorized_user_id: int = 0):
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )
        self._memory = ConversationMemory()  # Legacy system for backward compatibility
        self._session_manager = get_session_manager()
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

    def _estimate_tokens(self, messages: list) -> int:
        """Estimate token count for messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                # Rough estimation: Chinese chars ~2 tokens, English words ~1.5 tokens
                chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
                english_text = re.sub(r'[\u4e00-\u9fff]', '', content)
                english_words = len(re.findall(r'\b\w+\b', english_text))
                total += chinese_chars * 2 + english_words * 1.5
            elif isinstance(content, list):
                # For content blocks, extract text
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
                        english_text = re.sub(r'[\u4e00-\u9fff]', '', text)
                        english_words = len(re.findall(r'\b\w+\b', english_text))
                        total += chinese_chars * 2 + english_words * 1.5
        return int(total)

    def _adjust_messages_for_context(self, messages: list, max_tokens: int = constants.MAX_CONTEXT_WINDOW) -> list:
        """Reduce messages if token count exceeds limit."""
        estimated = self._estimate_tokens(messages)
        if estimated <= max_tokens:
            return messages

        logger.warning(f"Token estimate {estimated} exceeds limit {max_tokens}, reducing messages")

        # Check if first message is system message
        has_system = messages and messages[0].get("role") == "system"
        system_message = messages[0] if has_system else None
        other_messages = messages[1:] if has_system else messages

        # Try removing oldest non-system messages first
        for i in range(1, len(other_messages)):
            reduced = other_messages[i:]
            if has_system:
                reduced = [system_message] + reduced
            if self._estimate_tokens(reduced) <= max_tokens:
                return reduced

        # If still too large, keep system message (if any) and last non-system message
        if has_system:
            if other_messages:
                return [system_message, other_messages[-1]]
            else:
                return [system_message]
        else:
            return messages[-1:] if messages else []

    def _call_deepseek_api(self, messages: list, tools=None, max_tokens: int = constants.API_MAX_TOKENS):
        """Call DeepSeek API with automatic retry for transient errors.

        Args:
            messages: List of message dictionaries
            tools: Optional tools to include in the request
            max_tokens: Maximum tokens to generate

        Returns:
            API response object

        Raises:
            openai.BadRequestError: For client errors (including context length exceeded)
            Exception: For other errors after all retries exhausted
        """
        # Define retryable exceptions
        retryable_exceptions = (
            openai.APIConnectionError,  # Network errors
            openai.APITimeoutError,     # Timeout errors
            openai.RateLimitError,      # Rate limiting
            openai.InternalServerError, # 5xx server errors
        )

        # Create retry decorator
        retry_decorator = retry(
            max_retries=MAX_API_RETRIES,
            initial_delay=INITIAL_RETRY_DELAY,
            max_delay=MAX_RETRY_DELAY,
            backoff_factor=RETRY_BACKOFF_FACTOR,
            jitter=0.1,
            retryable_exceptions=retryable_exceptions,
            on_retry=lambda attempt, exc: logger.warning(
                f"DeepSeek API call failed, retry {attempt}/{MAX_API_RETRIES}: {exc}"
            )
        )

        # Define the API call function
        @retry_decorator
        def _api_call():
            return self._client.chat.completions.create(
                model=constants.DEEPSEEK_MODEL,
                max_tokens=max_tokens,
                tools=tools,
                messages=messages,
            )

        # Execute with retry
        try:
            return _api_call()
        except Exception as e:
            # Re-raise BadRequestError (including context_length_exceeded) without retry
            if isinstance(e, openai.BadRequestError):
                raise
            # For other exceptions, the retry decorator will have already handled them
            # If we get here, all retries were exhausted
            logger.error(f"DeepSeek API call failed after {MAX_API_RETRIES} retries: {e}")
            raise

    def _agentic_loop(self, messages: list, authorized: bool = False,
                     session_id: str = None) -> str:
        """Main agentic loop with context length handling."""
        system = get_system_prompt()
        clean_messages = self._sanitize_messages(messages)
        working_messages = [{"role": "system", "content": system}] + clean_messages

        for iteration in range(constants.MAX_TOOL_ITERATIONS):
            # Adjust messages if needed before API call
            adjusted_messages = self._adjust_messages_for_context(working_messages)

            try:
                response = self._call_deepseek_api(
                    messages=adjusted_messages,
                    tools=OPENAI_TOOL_DEFINITIONS,
                    max_tokens=MAX_TOKENS,
                )
            except openai.BadRequestError as e:
                if "context_length_exceeded" in str(e).lower():
                    logger.warning(f"Context length exceeded, retrying with reduced messages")
                    # Reduce messages and retry (up to constants.MAX_RETRIES_CONTEXT_EXCEEDED)
                    for retry in range(constants.MAX_RETRIES_CONTEXT_EXCEEDED):
                        # Reduce messages by half each retry, preserving system message
                        reduction_factor = 2 ** (retry + 1)  # 2, 4, 8
                        reduced_count = max(1, len(working_messages) // reduction_factor)

                        # Check if first message is system message
                        has_system = working_messages and working_messages[0].get("role") == "system"
                        if has_system:
                            system_message = working_messages[0]
                            # Keep system message + recent non-system messages
                            other_messages = working_messages[1:]
                            reduced_other = other_messages[-max(1, reduced_count - 1):] if other_messages else []
                            reduced_messages = [system_message] + reduced_other
                        else:
                            reduced_messages = working_messages[-reduced_count:]

                        logger.info(f"Retry {retry + 1}: Using {len(reduced_messages)} messages")

                        try:
                            response = self._call_deepseek_api(
                                messages=reduced_messages,
                                tools=OPENAI_TOOL_DEFINITIONS,
                                max_tokens=MAX_TOKENS,
                            )
                            # Success - continue with the response
                            break
                        except openai.BadRequestError as retry_e:
                            if "context_length_exceeded" in str(retry_e).lower() and retry < constants.MAX_RETRIES_CONTEXT_EXCEEDED - 1:
                                continue
                            else:
                                raise retry_e
                    else:
                        # All retries failed
                        logger.error(f"All context reduction retries failed")
                        return f"對話歷史過長，無法處理。請使用 /new 開始新對話。"
                else:
                    # Other BadRequestError
                    raise e
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

                if len(result) > constants.TOOL_RESULT_MAX_LEN:
                    result = result[:constants.TOOL_RESULT_MAX_LEN] + "\n...(輸出已截斷)"

                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        try:
            adjusted_messages = self._adjust_messages_for_context(working_messages)
            response = self._call_deepseek_api(
                messages=adjusted_messages,
                tools=None,
                max_tokens=MAX_TOKENS,
            )
            return response.choices[0].message.content or "任務已執行完畢。"
        except Exception as e:
            logger.error(f"Final API call failed: {e}")
            return "任務已執行，但無法生成最終回覆。"

    def chat(self, user_id: int, text: str, session_id: str = None) -> str:
        """
        Main chat method with session support.
        If session_id is provided, uses session manager. Otherwise uses legacy memory.
        """
        authorized = (user_id == self._authorized_user_id)

        if session_id:
            # Use session manager
            self._session_manager.add_message(session_id, "user", text)
            messages = self._session_manager.get_messages_for_api(
                session_id,
                max_messages=constants.DEFAULT_MAX_HISTORY_MESSAGES,
                max_tokens=constants.MAX_CONTEXT_WINDOW
            )
            reply = self._agentic_loop(messages, authorized=authorized, session_id=session_id)
            self._session_manager.add_message(session_id, "assistant", reply)
        else:
            # Legacy mode for backward compatibility
            self._memory.add_message(user_id, "user", text)
            reply = self._agentic_loop(self._memory.get_history(user_id), authorized=authorized)
            self._memory.add_message(user_id, "assistant", reply)

        return reply

    def chat_with_auto_session(self, user_id: int, text: str) -> Tuple[str, str]:
        """
        Automatically determine session based on message content.
        Returns (reply, session_id).
        """
        # Get or create session based on message
        session_id = self._session_manager.get_or_create_session(user_id, text)

        # Use the session for chat
        reply = self.chat(user_id, text, session_id)

        return reply, session_id

    def analyze_image(
        self, user_id: int, image_data: bytes, media_type: str, caption: str = ""
    ) -> tuple[str, str]:
        """
        Analyze an image and return (reply, session_id).
        """
        text = caption if caption else "收到一張圖片，但目前模型不支援圖片分析，請用文字描述圖片內容。"
        # Use auto session for image analysis
        reply, session_id = self.chat_with_auto_session(user_id, text)
        return reply, session_id

    def analyze_file(
        self, user_id: int, file_data: bytes, filename: str, caption: str = ""
    ) -> tuple[str, str]:
        """
        Analyze a file and return (reply, session_id).
        """
        if filename.lower().endswith(".pdf"):
            return self._analyze_pdf(user_id, file_data, caption)
        try:
            text_content = file_data.decode("utf-8")
        except UnicodeDecodeError:
            text_content = file_data.decode("latin-1")
        user_message = f"檔案名稱：{filename}\n\n檔案內容：\n{text_content}"
        if caption:
            user_message = f"{caption}\n\n{user_message}"
        # Use auto session for file analysis
        reply, session_id = self.chat_with_auto_session(user_id, user_message)
        return reply, session_id

    def _analyze_pdf(self, user_id: int, pdf_data: bytes, caption: str = "") -> tuple[str, str]:
        """
        Analyze a PDF file and return (reply, session_id).
        """
        try:
            import io
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(pdf_data))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            text_content = "\n\n".join(pages_text)
            if not text_content.strip():
                return "無法從 PDF 提取文字（可能是掃描圖片格式）。", ""
        except ImportError:
            return "PDF 解析需要安裝 pypdf：pip install pypdf", ""
        except Exception as e:
            return f"PDF 解析失敗：{e}", ""
        user_message = f"PDF 文件內容：\n\n{text_content[:8000]}"
        if caption:
            user_message = f"{caption}\n\n{user_message}"
        # Use auto session for PDF analysis
        reply, session_id = self.chat_with_auto_session(user_id, user_message)
        return reply, session_id

    def clear_memory(self, user_id: int) -> None:
        """Clear legacy memory for a user."""
        self._memory.clear(user_id)

    def create_new_session(self, user_id: int, task_type: str = None) -> str:
        """Manually create a new session for a user."""
        task_type_enum = None
        if task_type:
            try:
                task_type_enum = TaskType(task_type.lower())
            except ValueError:
                task_type_enum = TaskType.CHAT

        return self._session_manager.create_new_session(user_id, task_type_enum)

    def get_user_sessions(self, user_id: int, include_archived: bool = False) -> list:
        """Get all sessions for a user."""
        sessions = self._session_manager.get_user_sessions(user_id, include_archived)
        return [s.to_dict() for s in sessions]

    def get_session_summary(self, session_id: str) -> dict:
        """Get summary of a session."""
        return self._session_manager.get_session_summary(session_id)

    def get_current_session_id(self, user_id: int, text: str) -> str:
        """Get the session ID that would be used for a message (without creating one)."""
        return self._session_manager.get_or_create_session(user_id, text)