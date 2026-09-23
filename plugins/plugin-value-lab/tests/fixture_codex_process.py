"""Synthetic Codex event process. Never invokes Codex or a model service."""
import json
import sys
import uuid

prompt = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": str(uuid.uuid4())}), flush=True)
if "FAIL_INFRASTRUCTURE" in prompt:
    print(json.dumps({"type": "turn.failed", "error": {"message": "synthetic failure"}}), flush=True)
    sys.exit(1)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": '{"answer": 4}'}}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}), flush=True)
