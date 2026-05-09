# ORION Realtime Desktop Assistant

## Introduction
ORION is a realtime, voice-first desktop assistant inspired by Tony Stark-style AI systems. It combines a low-latency voice pipeline (STT -> LLM -> TTS) with an MCP tool backend so the assistant can not only talk, but also perform visible desktop actions during demos.

This project is intentionally lightweight and modular: one process hosts MCP tools and another process runs the LiveKit voice agent.

## Problem Statement
Most conversational assistants can answer text questions but struggle to demonstrate actionable desktop control in real time. For demo environments, you need a system that can:

1. Understand spoken commands quickly.
2. Trigger reliable tool actions (open URLs, search, launch apps).
3. Return spoken confirmations naturally.
4. Stay stable when one provider is unavailable.

## Proposed Solution
ORION uses a two-process architecture:

1. MCP Server (FastMCP): exposes tool APIs over SSE.
2. Voice Agent (LiveKit Agents): handles streaming audio, LLM reasoning, tool invocation, and speech synthesis.

The assistant supports realtime voice interaction and visible desktop actions such as:

1. Search Google.
2. Search YouTube.
3. Open websites.
4. Launch common Windows applications.
5. Open world and finance visual dashboards.

## System Specifications and Requirements

### Runtime Requirements
1. OS: Windows (primary demo target; app launcher mappings are Windows-oriented).
2. Python: 3.11+
3. Package manager: `uv`
4. Network access for LiveKit, LLM providers, and RSS/dashboard URLs.

### Required Environment Variables
1. `LIVEKIT_URL`
2. `LIVEKIT_API_KEY`
3. `LIVEKIT_API_SECRET`
4. `SARVAM_API_KEY`
5. `GROQ_API_KEY`

### Optional / Conditional Environment Variables
1. `OPENROUTER_API_KEY` (fallback only)
2. `DEEPGRAM_API_KEY`

### Installation
```bash
uv sync
```

### Run
Start MCP server:
```bash
uv run orion
```

Start voice agent (new terminal):
```bash
uv run orion_voice
```

Direct mode alternatives:
```bash
uv run agent_orion.py dev
uv run agent_orion.py console
```

## Key Features
1. Realtime voice conversation with STT, LLM reasoning, and TTS playback.
2. MCP-based modular tools (`orion/tools/*`) with clean registration.
3. Browser and desktop control tools for demo visibility:
  1. `search_google(query)`
  2. `search_youtube(query)`
  3. `open_website(url)`
  4. `open_app(app_name)`
4. News intelligence tools (`get_world_news`, `get_world_finance_news`).
5. Visual dashboard triggers (`open_world_monitor`, `open_finance_world_monitor`).
6. Provider flexibility:
  1. STT: Sarvam (default) or Whisper
  2. LLM: Groq (default), Gemini, or OpenAI
  3. TTS: Sarvam (default) or OpenAI
7. Controlled fallback behavior:
  1. Gemini fallback is now explicit via `ENABLE_LLM_FALLBACK=true`
  2. Placeholder Google keys are ignored for fallback

## System Architecture and Workflow

### Architecture
```text
 +----------------------+        +---------------------------+
 |   LiveKit Client     |        |     FastMCP Server        |
 | (Playground / Room)  |        |        (server.py)        |
 +----------+-----------+        +-------------+-------------+
        |                                  ^
        v                                  |
 +----------------------+   SSE Tool Calls     |
 |   agent_orion.py     +----------------------+
 |  (LiveKit Agent)     |
 |  - STT (Sarvam)      |
 |  - LLM (Groq, etc.)  |
 |  - TTS (Sarvam)      |
 +----------+-----------+
        |
        v
  Browser / Desktop Actions
```

### Workflow
1. User speaks in LiveKit room.
2. STT transcribes speech to text.
3. LLM interprets intent and decides whether a tool is required.
4. If needed, the agent calls MCP tools over SSE.
5. Tool executes action (fetch feed, open URL, launch app, etc.).
6. Tool response is returned to the agent.
7. LLM produces natural response.
8. TTS synthesizes audio reply.
9. Audio is streamed back to the user.

## Tech Stack
1. Language: Python 3.11+
2. Agent Runtime: LiveKit Agents
3. Tooling Protocol: FastMCP (SSE transport)
4. STT: Sarvam Saaras v3 (default)
5. LLM: Groq Llama 3.3 70B Versatile (default), OpenRouter DeepSeek fallback
6. TTS: Sarvam Bulbul v2 (default)
7. HTTP Client: `httpx`
8. Utility Modules: `webbrowser`, `subprocess`, `urllib.parse`
9. Env Management: `python-dotenv`
10. Dependency/Run Tool: `uv`

## Performance Evaluation

### What to Measure
1. End-to-end response latency (speech start to first audio response).
2. STT transcript delay.
3. Tool call round-trip time (agent -> MCP -> agent).
4. Tool success rate (open app, open website, searches).
5. Session stability (disconnects, retries, fallback events).

### Current Observations (from logs)
1. End-to-end behavior is stable for demo flow: speech is captured, transcribed, processed, and played back reliably.
2. STT is streaming continuously and detecting speech boundaries correctly in normal usage.
3. Transcript delays are typically around sub-second to low-second range, which feels responsive for realtime interaction.
4. Tool execution paths (news, browser open, app launch) are working as expected in standard scenarios.
5. A few minor bugs remain, mostly around configuration edge cases (for example invalid fallback API keys or provider toggles), but core assistant behavior is functioning well.

### Recommended Demo Benchmarks
1. Median transcript delay: < 1.2s
2. Median tool execution feedback: < 1.0s
3. Successful tool invocation rate: > 95% over 20 scripted commands
4. Session uptime during demo: 15+ minutes without agent crash

## Repository Structure
```text
friday-tony-stark-demo/
|-- server.py
|-- agent_orion.py
|-- main.py
|-- pyproject.toml
|-- README.md
`-- orion/
   |-- config.py
   |-- prompts/
   |   `-- templates.py
   |-- resources/
   |   `-- data.py
   `-- tools/
      |-- __init__.py
      |-- web.py
      |-- browser.py
      |-- system.py
      `-- utils.py
```

## Tooling Notes
1. `orion/tools/browser.py` provides demo-friendly browser and app-launch actions.
2. `orion/tools/web.py` handles world and finance feed retrieval and dashboard launch.
3. `orion/tools/__init__.py` is the registration hub for all tool modules.

## Known Limitations
1. `search_web` in `orion/tools/web.py` remains a stub.
2. Some app launch commands depend on app availability in system PATH.
3. Network outages or API quota limits can affect provider behavior.

## Future Improvements
1. Implement robust web search in `search_web` with a provider-backed API.
2. Add structured latency logging and benchmark scripts.
3. Add lightweight health checks for provider credentials before session start.
