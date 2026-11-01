"""Agent executor: Google GenAI API loop with persona, tools and memory."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError

from src.agent.prompts import SYSTEM_PROMPT
from src.config import MAX_HISTORY_MESSAGES, MAX_TOOL_ROUNDS, MODEL, TEMPERATURE
from src.tools import TOOLS, execute_tool

FALLBACK_REPLY = (
    "Desculpe, tive um probleminha para concluir sua consulta agora. "
    "Pode repetir ou reformular a pergunta, por favor? 🎶"
)


class EmporioAgent:
    """Stateful conversational agent powered by Google Gemini."""

    def __init__(
        self,
        model: str | None = None,
        on_tool_call: Callable[[str, dict[str, Any], str], None] | None = None,
    ) -> None:
        self.model = model or MODEL

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY não configurada no ambiente ou ficheiro .env")

        self.client = genai.Client(api_key=api_key)
        self.on_tool_call = on_tool_call
        self.tools_map: dict[str, Callable[..., Any]] = TOOLS
        self._init_chat()

    def _init_chat(self, history: list[types.Content] | None = None) -> None:
        """Inicializa a sessão de chat com as instruções de sistema e ferramentas."""
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=TEMPERATURE,
            tools=list(self.tools_map.values()),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.chat_session = self.client.chats.create(
            model=self.model,
            config=config,
            history=history,
        )

    def _trim_history(self) -> None:
        history = self.chat_session.get_history()
        if len(history) <= MAX_HISTORY_MESSAGES:
            return

        history = history[-MAX_HISTORY_MESSAGES:]
        while history and (
            history[0].role != "user"
            or not history[0].parts
            or history[0].parts[0].text is None
        ):
            history.pop(0)
        self._init_chat(history)

    def reset(self) -> None:
        """Reinicia a sessão de conversa limpando o histórico."""
        self._init_chat()

    def chat(self, user_message: str) -> str:
        """Envia a mensagem do usuário e processa as chamadas de ferramentas iterativamente."""
        try:
            response = self.chat_session.send_message(user_message)

            for _ in range(MAX_TOOL_ROUNDS):
                calls = response.function_calls
                if not calls:
                    break

                function_responses = []
                for call in calls:
                    fn_name = call.name
                    if not fn_name:
                        raise RuntimeError("Gemini retornou uma chamada de ferramenta sem nome.")
                    fn_args = dict(call.args) if call.args else {}
                    result_str = execute_tool(fn_name, json.dumps(fn_args, ensure_ascii=False))

                    if self.on_tool_call:
                        self.on_tool_call(fn_name, fn_args, result_str)

                    function_responses.append(
                        types.Part.from_function_response(
                            name=fn_name,
                            response=json.loads(result_str),
                        )
                    )
                response = self.chat_session.send_message(function_responses)
                time.sleep(2)

            answer = response.text.strip() if response.text else FALLBACK_REPLY
            self._trim_history()
            return answer

        except APIError as exc:
            return f"{FALLBACK_REPLY} (Erro: {exc})"