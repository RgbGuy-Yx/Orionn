import re
with open("agent_orion.py", "r", encoding="utf-8") as f:
    text = f.read()

pattern = r"            logger\.warning\(\"Groq request failed[^\n]+?\n            try:\n                async for chunk in _stream_openrouter_response(?:.*?)(?=    async def on_enter)"
replacement = """            logger.warning(\"Groq request failed (%s); switching to OpenRouter fallback.\", exc)
            try:
                async for chunk in _stream_openrouter_response(chat_ctx):
                    yield chunk
            except Exception as fallback_exc:
                logger.exception(\"OpenRouter fallback failed.\")
                from livekit.agents.llm import ChatChunk, ChoiceDelta
                import uuid
                yield ChatChunk(id=str(uuid.uuid4()), delta=ChoiceDelta(role=\"assistant\", content=\"I am having complete system failure. Backup servers are unresponsive.\"))

"""

text = re.sub(pattern, replacement, text, flags=re.DOTALL)
with open("agent_orion.py", "w", encoding="utf-8") as f:
    f.write(text)

