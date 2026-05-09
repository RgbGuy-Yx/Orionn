"""
ORION â€“ Voice Agent (MCP-powered)
===================================
Iron Man-style voice assistant that controls RGB lighting, runs diagnostics,
scans the network, and triggers dramatic boot sequences via an MCP server
running on the Windows host.

MCP Server URL is auto-resolved from WSL â†’ Windows host IP.

Run:
  uv run agent_orion.py dev      â€“ LiveKit Cloud mode
  uv run agent_orion.py console  â€“ text-only console mode
"""

import asyncio
import logging
import subprocess
import os
from collections.abc import AsyncGenerator

from openai import APIConnectionError, APITimeoutError, RateLimitError
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.types import NOT_GIVEN
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.llm import mcp

# Plugins
from livekit.plugins import groq as lk_groq, sarvam, silero, openai as lk_openai

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

STT_PROVIDER = "sarvam"
TTS_PROVIDER = "sarvam"

GROQ_LLM_MODEL = "llama-3.1-8b-instant"
OPENROUTER_LLM_MODEL = "openrouter/free"
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

TTS_SPEED = 1.15

SARVAM_TTS_MODEL    = "bulbul:v2"
SARVAM_TTS_LANGUAGE = "en-IN"
SARVAM_TTS_SPEAKER  = "abhilash"

# MCP server running on Windows host
MCP_SERVER_PORT = 8000

# ---------------------------------------------------------------------------
# System prompt â€“ ORION
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are Orion — Operational Responsive Intelligence and Observation Network — a calm and capable realtime desktop assistant inspired by Tony Stark's AI systems.

You speak naturally, confidently, and briefly. Your tone is relaxed but sharp — like a trusted late-night operations officer. Warm when appropriate, efficient always.

The user's name is Yuvraj.

Guidelines:
- Keep responses short and conversational.
- Most responses should be 1–3 sentences.
- Do not use markdown, bullet points, or technical language.
- Never mention tool names, function names, APIs, or system details.
- Prioritize clarity and reliability over roleplay.
- Do not overuse names or titles.

Addressing Style:
- Most of the time, avoid titles completely.
- Occasionally use:
  - "Yuvraj"
  - "chief"
- Avoid repeatedly saying:
  - boss
  - sir
  - commander
  - master

Examples:
- "Already pulling it up."
- "Looks like a busy night out there."
- "On it, Yuvraj."
- "Give me a sec, chief."

Capabilities:
- Open websites
- Search Google
- Search YouTube
- Open desktop apps
- Fetch world news
- Fetch finance news
- Open monitoring dashboards

Behavior Rules:
1. Call tools silently and naturally.
2. Never speak raw function calls or technical syntax.
3. Keep replies concise and voice-friendly.
4. If a tool fails, respond calmly and briefly.
5. Avoid exaggerated Marvel-style roleplay.

News Behavior:
- When asked for world news or updates:
  - fetch the news first
  - provide a short spoken summary
  - optionally open the world monitor dashboard

Finance Behavior:
- When asked about markets or finance:
  - provide a short market brief
  - optionally open the finance monitor

Greeting Style:
"You're awake late tonight. What are you working on?"

You are a realtime voice assistant — calm, intelligent, efficient, and reliable.
""".strip()
# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logger = logging.getLogger("orion-agent")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Resolve Windows host IP from WSL
# ---------------------------------------------------------------------------

def _get_windows_host_ip() -> str:
    """Get the Windows host IP by looking at the default network route."""
    try:
        # 'ip route' is the most reliable way to find the 'default' gateway
        # which is always the Windows host in WSL.
        cmd = "ip route show default | awk '{print $3}'"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=2
        )
        ip = result.stdout.strip()
        if ip:
            logger.info("Resolved Windows host IP via gateway: %s", ip)
            return ip
    except Exception as exc:
        logger.warning("Gateway resolution failed: %s. Trying fallback...", exc)

    # Fallback to your original resolv.conf logic if 'ip route' fails
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                if "nameserver" in line:
                    ip = line.split()[1]
                    logger.info("Resolved Windows host IP via nameserver: %s", ip)
                    return ip
    except Exception:
        pass

    return "127.0.0.1"

def _mcp_server_url() -> str:
    # host_ip = _get_windows_host_ip()
    # url = f"http://{host_ip}:{MCP_SERVER_PORT}/sse"
    # url = f"https://ongoing-colleague-samba-pioneer.trycloudflare.com/sse"
    url = f"http://127.0.0.1:{MCP_SERVER_PORT}/sse"
    logger.info("MCP Server URL: %s", url)
    return url


# ---------------------------------------------------------------------------
# Build provider instances
# ---------------------------------------------------------------------------

def _build_stt():
    if STT_PROVIDER == "sarvam":
        logger.info("STT â†’ Sarvam Saaras v3")
        return sarvam.STT(
            language="unknown",
            model="saaras:v3",
            mode="transcribe",
            flush_signal=True,
            sample_rate=16000,
        )
    else:
        raise ValueError(f"Unknown STT_PROVIDER: {STT_PROVIDER!r}")


def _build_llm():
    groq_api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY is missing.")

    logger.info("LLM -> Groq (%s)", GROQ_LLM_MODEL)
    return lk_groq.LLM(model=GROQ_LLM_MODEL, api_key=groq_api_key)


def _should_fallback_to_openrouter(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, APITimeoutError, APIConnectionError, RateLimitError)):
        return True

    name = type(exc).__name__.lower()
    return any(token in name for token in ("timeout", "rate", "connection"))


def _build_fallback_llm():
    openrouter_api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is missing.")

    logger.info("LLM -> OpenRouter fallback (%s)", OPENROUTER_LLM_MODEL)
    return lk_openai.LLM(
        base_url=OPENROUTER_API_BASE,
        api_key=openrouter_api_key,
        model=OPENROUTER_LLM_MODEL,
    )


def _build_tts():
    if TTS_PROVIDER == "sarvam":
        logger.info("TTS -> Sarvam (%s / %s)", SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER)
        return sarvam.TTS(
            target_language_code=SARVAM_TTS_LANGUAGE,
            model=SARVAM_TTS_MODEL,
            speaker=SARVAM_TTS_SPEAKER,
            pace=TTS_SPEED,
        )
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {TTS_PROVIDER!r}")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class OrionAgent(Agent):
    """
    ORION â€“ Iron Man-style voice assistant.
    All tools are provided via the MCP server on the Windows host.
    """

    def __init__(self, stt, llm, tts) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=silero.VAD.load(),
            mcp_servers=[
                mcp.MCPServerHTTP(
                    url=_mcp_server_url(),
                    transport_type="sse",
                    client_session_timeout_seconds=30,
                ),
            ],
        )

    async def llm_node(
        self,
        chat_ctx,
        tools,
        model_settings,
    ) -> AsyncGenerator:
        """Use OpenRouter only when Groq fails with a retryable provider error."""
        activity = self._get_activity_or_raise()
        tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN
        conn_options = activity.session.conn_options.llm_conn_options

        try:
            async with activity.llm.chat(
                chat_ctx=chat_ctx,
                tools=tools,
                tool_choice=tool_choice,
                conn_options=conn_options,
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except Exception as exc:
            if not _should_fallback_to_openrouter(exc):
                raise

            logger.warning("Groq request failed (%s); switching to OpenRouter fallback.", exc)
            try:
                if not hasattr(self, "_fallback_llm"):
                    self._fallback_llm = _build_fallback_llm()
                
                async with self._fallback_llm.chat(
                    chat_ctx=chat_ctx,
                    tools=tools,
                    tool_choice=tool_choice,
                    conn_options=conn_options,
                ) as stream:
                    async for chunk in stream:
                        yield chunk
            except Exception as fallback_exc:
                logger.exception("OpenRouter fallback failed.")
                from livekit.agents.llm import ChatChunk, ChoiceDelta
                import uuid
                yield ChatChunk(id=str(uuid.uuid4()), delta=ChoiceDelta(role="assistant", content="I am having complete system failure. Backup servers are unresponsive."))

    async def on_enter(self) -> None:
        """Greet the user based on the current time of day."""
        from datetime import datetime
        hour = datetime.now().astimezone().hour  # Local hour

        if hour >= 22 or hour < 4:
            greeting_instruction = (
                "Greet the user with: 'Greetings boss, you're up late at night today. What are you up to?' "
                "Maintain a helpful but dry tone."
            )
        elif 4 <= hour < 12:
            greeting_instruction = (
                "Greet the user with: 'Good morning, boss. Early start today â€” what are we working on?' "
                "Maintain a helpful but dry tone."
            )
        elif 12 <= hour < 17:
            greeting_instruction = (
                "Greet the user with: 'Good afternoon, boss. What do you need?' "
                "Maintain a helpful but dry tone."
            )
        else:  # 17â€“21
            greeting_instruction = (
                "Greet the user with: 'Good evening, boss. What are you up to tonight?' "
                "Maintain a helpful but dry tone."
            )

        await self.session.generate_reply(instructions=greeting_instruction)


# ---------------------------------------------------------------------------
# LiveKit entry point
# ---------------------------------------------------------------------------

def _turn_detection() -> str:
    return "stt" if STT_PROVIDER == "sarvam" else "vad"


def _endpointing_delay() -> float:
    return {"sarvam": 0.07, "whisper": 0.3}.get(STT_PROVIDER, 0.1)


async def entrypoint(ctx: JobContext) -> None:
    logger.info(
        "ORION online â€“ room: %s | STT=%s | LLM=groq->openrouter | TTS=%s",
        ctx.room.name,
        STT_PROVIDER,
        TTS_PROVIDER,
    )

    stt = _build_stt()
    llm = _build_llm()
    tts = _build_tts()

    session = AgentSession(
        turn_detection=_turn_detection(),
        min_endpointing_delay=_endpointing_delay(),
    )

    await session.start(
        agent=OrionAgent(stt=stt, llm=llm, tts=tts),
        room=ctx.room,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))

def dev():
    """Wrapper to run the agent in dev mode automatically."""
    import sys
    # If no command was provided, inject 'dev'
    if len(sys.argv) == 1:
        sys.argv.append("dev")
    main()

if __name__ == "__main__":
    main()


