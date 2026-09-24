"""Observe exact Bash calls without executing scripts or trusting final prose."""
import json

from .claude_collection import observe_native_events


def observe_execution(text, expected, artifacts):
    result = {"status": "UNKNOWN", "command": expected["command"], "calls": [],
              "terminal_status": "UNKNOWN", "model_conflict_observed": False,
              "script": artifacts.get(expected["script_artifact"]),
              "authenticated_execution": False,
              "scope": "Tool results are operator-supplied observations; final script bytes do not prove the bytes executed, isolation or scientific validity."}
    if text is None:
        return result
    observation = observe_native_events(text)
    if not observation.get("session_id"):
        return result
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    terminal = [e for e in events if e.get("type") == "result"]
    if len(terminal) == 1:
        end = terminal[0]
        if end.get("is_error") is True:
            result["terminal_status"] = "ERROR"
        elif end.get("is_error") is False and end.get("subtype") == "success":
            result["terminal_status"] = "SUCCESS"
    calls, replies = {}, {}
    ambiguous = False
    terminal_index = next((i for i, e in enumerate(events) if e.get("type") == "result"), len(events))
    for event_index, event in enumerate(events):
        message = event.get("message")
        if (event.get("type") == "assistant" and isinstance(message, dict)
                and message.get("model") is not None and message["model"] != observation.get("model")):
            result["model_conflict_observed"] = True
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict):
                continue
            if event_index > terminal_index and block.get("type") in ("tool_use", "tool_result"):
                ambiguous = True
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                cid = block.get("id")
                if not isinstance(cid, str) or not cid or cid in calls:
                    ambiguous = True
                    continue
                calls[cid] = (event_index, block)
            if event.get("type") == "user" and block.get("type") == "tool_result":
                cid = block.get("tool_use_id")
                if not isinstance(cid, str) or not cid or cid in replies:
                    ambiguous = True
                    continue
                replies[cid] = (event_index, block)
    for cid, (index, call) in calls.items():
        args = call.get("input")
        if call.get("name") != "Bash" or not isinstance(args, dict) or args.get("command") != expected["command"]:
            continue
        reply_index, reply = replies.get(cid, (-1, {}))
        state = "UNKNOWN"
        if reply_index > index and type(reply.get("is_error")) is bool:
            # Background launches do not establish completion of the script.
            if args.get("run_in_background") is not True:
                state = "TOOL_ERROR" if reply["is_error"] else "TOOL_REPORTED_SUCCESS"
        result["calls"].append({"tool_use_id": cid, "call_event": index,
                                "result_event": reply_index if reply else None, "status": state})
    if not ambiguous and result["script"] is not None and result["calls"]:
        states = [c["status"] for c in result["calls"]]
        # Retain an earlier failure even when a later attempt succeeds.
        result["status"] = ("TOOL_ERROR" if "TOOL_ERROR" in states else
                            "TOOL_REPORTED_SUCCESS" if all(s == "TOOL_REPORTED_SUCCESS" for s in states) else "UNKNOWN")
    elif not ambiguous and not result["calls"]:
        result["status"] = "NOT_OBSERVED"
    return result
