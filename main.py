#!/usr/bin/env python3
"""CLI to chat with the Empório da Música virtual assistant."""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.agent import EmporioAgent  # noqa: E402
from src.agent.prompts import AGENT_NAME, STORE_NAME  # noqa: E402
from src.config import MODEL  # noqa: E402

BANNER = f"""\
🎸 {STORE_NAME} — atendimento virtual com {AGENT_NAME}
Comandos: /reset (nova conversa) · /sair (encerrar)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{STORE_NAME} virtual assistant (CLI)")
    parser.add_argument("--model", default=MODEL, help=f"Gemini model (default: {MODEL})")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show tool calls and raw results")
    args = parser.parse_args()

    if not os.getenv("GOOGLE_API_KEY"):
        print("GOOGLE_API_KEY não configurada. Copie .env.example para .env e informe sua chave.", file=sys.stderr)
        return 1

    def show_tool(name: str, arguments: dict, result: str) -> None:
        preview = result if len(result) < 600 else result[:600] + " …"
        print(f"   \033[2m🔧 {name}({arguments})\n      → {preview}\033[0m")

    agent = EmporioAgent(model=args.model, on_tool_call=show_tool if args.verbose else None)
    print(BANNER)
    print(f"{AGENT_NAME}: Olá! Bem-vindo(a) ao {STORE_NAME}! Como posso te ajudar hoje? 🎶\n")

    while True:
        try:
            user = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté logo! 🎵")
            return 0
        if not user:
            continue
        if user.lower() in {"/sair", "/exit", "/quit"}:
            print(f"{AGENT_NAME}: Até logo! Foi um prazer. Volte sempre ao {STORE_NAME}! 🎵")
            return 0
        if user.lower() == "/reset":
            agent.reset()
            print("— conversa reiniciada —\n")
            continue
        try:
            print(f"\n{AGENT_NAME}: {agent.chat(user)}\n")
        except Exception as exc:  # network/API errors shouldn't kill the session
            print(f"\n[erro] {type(exc).__name__}: {exc}\n", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
