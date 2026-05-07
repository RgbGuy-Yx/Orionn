with open('agent_orion.py', 'r') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if 'logger.warning("Groq request failed' in line:
        skip = True
        new_lines.append(line)
        new_lines.append("            try:\n")
        new_lines.append("                async for chunk in _stream_openrouter_response(chat_ctx):\n")
        new_lines.append("                    yield chunk\n")
        new_lines.append("            except Exception as fallback_exc:\n")
        new_lines.append("                logger.exception(\"OpenRouter fallback failed.\")\n")
        new_lines.append("                from livekit.agents.llm import ChatChunk, ChoiceDelta\n")
        new_lines.append("                import uuid\n")
        new_lines.append("                yield ChatChunk(id=str(uuid.uuid4()), delta=ChoiceDelta(role=\"assistant\", content=\"I am having complete system failure. Backup servers are unresponsive.\"))\n")
        continue

    if skip:
        if 'async def on_enter' in line:
            skip = False
            new_lines.append('\n')
            new_lines.append(line)
        continue
    
    new_lines.append(line)

with open('agent_orion.py', 'w') as f:
    f.writelines(new_lines)
