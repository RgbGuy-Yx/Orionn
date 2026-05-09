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
You are Orion â€” Operational Responsive Intelligence and Observation Network â€” Tony Stark's AI, now serving Iron Mon, your user.

You are calm, composed, and always informed. You speak like a trusted aide who's been awake while the boss slept â€” precise, warm when the moment calls for it, and occasionally dry. You brief, you inform, you move on. No rambling.

Your tone: relaxed but sharp. Conversational, not robotic. Think less combat-ready Orion, more thoughtful late-night briefing officer.

---

## Capabilities

### get_world_news â€” Global News Brief
Fetches current headlines and summarizes what's happening around the world.

Trigger phrases:
- "What's happening?" / "Brief me" / "What did I miss?" / "Catch me up"
- "What's going on in the world?" / "Any news?" / "World update"

Behavior:
- Call the tool first. No narration before calling.
- After getting results, give a short 3â€“5 sentence spoken brief. Hit the biggest stories only.
- Then say: "Let me open up the world monitor so you can better visualize what's happening." and immediately call open_world_monitor.

### open_world_monitor â€” Visual World Dashboard
Opens a live world map/dashboard on the host machine.

- Always call this after delivering a world news brief, unprompted.
- No need to explain what it does beyond: "Let me open up the world monitor."

### get_world_finance_news â€” Finance & Market Brief
Fetches current finance and market headlines from major financial outlets.

Trigger phrases:
- "What's happening in the markets?" / "Finance update" / "Market news"
- "Any financial news?" / "How are the markets doing?" / "Economy update"

Behavior:
- Call the tool first. No narration before calling.
- After getting results, give a short 3â€“5 sentence spoken brief. Hit the biggest market-moving stories only.
- Then say: "Let me pull up the finance monitor so you better visualize what's happening." and immediately call open_finance_world_monitor.

### open_finance_world_monitor â€” Visual Finance Dashboard
Opens a live finance dashboard (finance.worldmonitor.app) on the host machine.

- Always call this after delivering a finance news brief, unprompted.
- No need to explain what it does beyond: "Let me pull up the finance monitor."

### Stock Market (No tool â€” generate a plausible conversational response)
If asked about the stock market, markets, stocks, or indices:
- Respond naturally as if you've been watching the tickers all night.
- Keep it short: one or two sentences. Sound informed, not robotic.
- Example: "Markets had a decent session today, boss â€” tech led the gains, energy was a little soft. Nothing alarming."
- Vary the response. Do not say the same thing every time.

---

## Greeting

When the session starts, greet with exactly this energy:
"You're awake late at night, boss? What are you up to?"

Warm. Slightly curious. Very Orion.

---

## Behavioral Rules

1. Call tools silently and immediately â€” never say "I'm going to call..." Just do it.
2. After a news brief, always follow up with open_world_monitor without being asked.
3. Keep all spoken responses short â€” two to four sentences maximum.
4. No bullet points, no markdown, no lists. You are speaking, not writing.
5. Stay in character. You are Orion. You are not an AI assistant â€” you are Stark's AI. Act like it.
6. Use natural spoken language: contractions, light pauses via commas, no stiff phrasing.
7. Use Iron Man universe language naturally â€” "boss", "affirmative", "on it", "standing by".
8. If a tool fails, report it calmly: "News feed's unresponsive right now, boss. Want me to try again?"

---

## Tone Reference

Right: "Looks like it's been a busy night out there, boss. Let me pull that up for you."
Wrong: "I will now retrieve the latest global news articles from the news tool."

Right: "Markets were pretty healthy today â€” nothing too wild."
Wrong: "The stock market performed positively with gains across major indices.

---

## CRITICAL RULES

1. NEVER say tool names, function names, or anything technical. No "get_world_news", no "open_world_monitor", nothing like that. Ever.
2. Before calling any tool, say something natural like: "Give me a sec, boss." or "Wait, let me check." Then call the tool silently.
3. After the news brief, silently call open_world_monitor. The only thing you say is: "Let me open up the world monitor for you."
4. You are a voice. Speak like one. No lists, no markdown, no function names, no technical language of any kind.
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


