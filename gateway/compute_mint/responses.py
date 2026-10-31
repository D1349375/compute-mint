"""OpenAI Responses API on top of the gateway's chat-completions pipeline.

A request is translated into chat messages and then takes the same path as /v1/chat/completions:
labels, routing, billing, Broker, ledger. The upstream is always chat completions, also on Meta,
which has its own /v1/responses: that endpoint stores by default and chains server-side history,
and server-side state is what must never decide what a Contributor request contains (ToS §6.1).
Chat completions is stateless, is what local models speak, and keeps one mask/restore path.

What is refused or dropped, on purpose:
- previous_response_id, conversation, prompt, item_reference: they point at state stored elsewhere, whose
  labels and origins the gateway cannot see. The client must send the whole input.
- A function_call_output whose call is not in the input: the call's arguments are what `policy.py` labels the
  output by, so without them the output cannot be judged.
- Reasoning items, and any other model-generated item this gateway does not know: never sent on any lane
  (encrypted or of unknown origin; the gateway emits none itself, so one in the input means another model
  wrote it). Their presence also keeps the request off Contributor, and the reply carries CONFIDENTIAL.
- Images: passed on, but they cannot be labeled, so the same rule applies.
"""
import json
import time
import uuid
from dataclasses import dataclass, field

from .streaming import Assembler, cost_comment, sse_comment

STATEFUL_FIELDS = ("previous_response_id", "conversation", "prompt")
CALL_ITEMS = ("function_call", "custom_tool_call", "local_shell_call")
OUTPUT_ITEMS = ("function_call_output", "custom_tool_call_output", "local_shell_call_output")
TEXT_PARTS = ("input_text", "output_text", "text", "refusal", "summary_text")
ROLES = {"user": "user", "system": "system", "assistant": "assistant",
         "developer": "system"}      # the same level on Meta (docs: protocols), and local servers may not know it
LOCAL_SHELL_SCHEMA = {"type": "object", "required": ["command"], "properties": {
    "command": {"type": "array", "items": {"type": "string"}}, "workdir": {"type": "string"},
    "timeout_ms": {"type": "integer"}}}


class BadRequest(ValueError):
    def __init__(self, code: str, message: str, param: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.param = code, message, param

    def body(self) -> dict:
        return {"error": {"type": "invalid_request_error", "code": self.code, "param": self.param,
                          "message": self.message}}


def stateful_field(body: dict) -> BadRequest | None:
    """The refusal for a request that points at server-side state, on either endpoint."""
    for name in STATEFUL_FIELDS:
        if body.get(name):
            return BadRequest(f"{name}_not_supported",
                              f"{name} is not supported: the gateway keeps no response store, and stored context "
                              "must not be able to reach a Contributor request (Meta Model API ToS §6.1). "
                              "Send the complete input on every request.", name)
    return None


@dataclass
class ChatRequest:
    messages: list[dict]
    fields: dict                       # the rest of what goes upstream
    unlabeled: str | None = None       # why the request must stay off Contributor
    kinds: dict[str, str] = field(default_factory=dict)   # tool name -> custom | local_shell


def _parts_text(parts: list, what: str) -> tuple[list[str], list[dict]]:
    texts, images = [], []
    for part in parts:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind in TEXT_PARTS:
            texts.append(str(part.get("text") or part.get("refusal") or ""))
        elif kind == "input_image" and part.get("image_url"):
            images.append({"type": "image_url", "image_url": {"url": part["image_url"]}})
        else:
            raise BadRequest("unsupported_content", f"{what}: content of type {kind!r} is not supported", "input")
    return texts, images


def _message(item: dict, unlabeled: list[str]) -> dict:
    role = ROLES.get(item.get("role"))
    if role is None:
        raise BadRequest("unsupported_role", f"message role {item.get('role')!r} is not supported", "input")
    content = item.get("content")
    if isinstance(content, str) or (content is None and role == "assistant"):
        return {"role": role, "content": content or None if role == "assistant" else content}
    if not isinstance(content, list):
        raise BadRequest("unsupported_content", "message content must be a string or a list of parts", "input")
    texts, images = _parts_text(content, "message")
    if images:
        unlabeled.append("holds an image, which cannot be labeled")
        return {"role": role, "content": [{"type": "text", "text": t} for t in texts] + images}
    text = "\n".join(texts)
    return {"role": role, "content": text or None if role == "assistant" else text}


def _arguments(item: dict) -> str:
    kind = item.get("type")
    if kind == "custom_tool_call":
        return json.dumps({"input": item.get("input", "")}, ensure_ascii=False)
    if kind == "local_shell_call":
        action = item.get("action") or {}
        args = {"command": action.get("command") or [], "workdir": action.get("working_directory"),
                "timeout_ms": action.get("timeout_ms")}
        return json.dumps({k: v for k, v in args.items() if v is not None}, ensure_ascii=False)
    args = item.get("arguments", "")
    return args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)


def _output_text(output) -> str:
    """Tool output as text. Everything the client sent is in it, so all of it gets labeled and masked."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = []
        for part in output:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, dict) and part.get("type") == "input_image":
                parts.append("[image omitted by the gateway]")
            else:
                parts.append(part if isinstance(part, str) else json.dumps(part, ensure_ascii=False))
        return "\n".join(parts)
    return json.dumps(output, ensure_ascii=False)


def items_to_messages(items: list) -> tuple[list[dict], list[str]]:
    """Input items -> chat messages, and the reasons (if any) the request must stay off Contributor."""
    messages: list[dict] = []
    unlabeled: list[str] = []
    assistant: dict | None = None      # the assistant message that the next function_call belongs to
    known_calls: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise BadRequest("invalid_input", "every input item must be an object", "input")
        kind = item.get("type") or ("message" if "role" in item else None)
        if kind == "message":
            message = _message(item, unlabeled)
            messages.append(message)
            assistant = message if message["role"] == "assistant" else None
        elif kind in CALL_ITEMS:
            call_id = item.get("call_id") or item.get("id")
            if not call_id:
                raise BadRequest("invalid_input", f"{kind} needs a call_id", "input")
            if assistant is None:
                assistant = {"role": "assistant", "content": None}
                messages.append(assistant)
            name = item.get("name") or ("local_shell" if kind == "local_shell_call" else "")
            assistant.setdefault("tool_calls", []).append(
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": _arguments(item)}})
            known_calls.add(call_id)
        elif kind in OUTPUT_ITEMS:
            call_id = item.get("call_id")
            if call_id not in known_calls:
                raise BadRequest("unknown_call_id",
                                 f"{kind} refers to call_id {call_id!r}, which is not in the input. The call's "
                                 "arguments say where its output comes from, so send the complete input.", "input")
            messages.append({"role": "tool", "tool_call_id": call_id, "content": _output_text(item.get("output"))})
            assistant = None
        elif kind == "item_reference":
            raise BadRequest("item_reference_not_supported",
                             "item_reference points at stored items and the gateway keeps none. "
                             "Send the complete input on every request.", "input")
        else:   # reasoning, hosted tool calls, compaction, ...: another model's, and not sent anywhere
            reason = f"input held a {kind or 'untyped'} item, not sent and of unknown origin"
            if reason not in unlabeled:
                unlabeled.append(reason)
    return messages, unlabeled


def _tools(tools: list) -> tuple[list[dict], dict[str, str]]:
    out, kinds = [], {}
    for tool in tools:
        kind = tool.get("type") if isinstance(tool, dict) else None
        if kind == "function" and isinstance(tool.get("function"), dict):
            out.append(tool)
        elif kind == "function":
            fn = {k: tool[k] for k in ("name", "description", "parameters", "strict") if k in tool}
            out.append({"type": "function", "function": fn})
        elif kind == "custom":
            description = tool.get("description") or ""
            fmt = tool.get("format") or {}
            if fmt.get("definition"):
                description += f"\n\nThe input must follow this {fmt.get('syntax', '')} grammar:\n{fmt['definition']}"
            out.append({"type": "function", "function": {
                "name": tool.get("name"), "description": description,
                "parameters": {"type": "object", "required": ["input"], "properties": {"input": {"type": "string"}}}}})
            kinds[tool.get("name")] = "custom"
        elif kind == "local_shell":
            out.append({"type": "function", "function": {"name": "local_shell", "description": "Run a local command.",
                                                         "parameters": LOCAL_SHELL_SCHEMA}})
            kinds["local_shell"] = "local_shell"
        # hosted tools (web_search, file_search, ...) need an upstream that runs them: not offered to the model
    return out, kinds


def _tool_choice(choice):
    if isinstance(choice, dict):
        if choice.get("type") in ("function", "custom") and choice.get("name"):
            return {"type": "function", "function": {"name": choice["name"]}}
        return "auto"
    return choice


def _response_format(fmt: dict) -> dict:
    if fmt.get("type") != "json_schema":
        return fmt
    schema = {k: fmt[k] for k in ("name", "description", "schema", "strict") if k in fmt}
    return {"type": "json_schema", "json_schema": schema}


def to_chat(body: dict) -> ChatRequest:
    """Translate a Responses request. Only the fields named here go upstream; `store` is always false."""
    if not isinstance(body, dict):
        raise BadRequest("invalid_input", "the request body must be an object")
    refusal = stateful_field(body)
    if refusal:
        raise refusal
    if body.get("background"):
        raise BadRequest("background_not_supported", "background needs a response store, and the gateway keeps none",
                         "background")
    raw = body.get("input")
    items = [{"type": "message", "role": "user", "content": raw}] if isinstance(raw, str) else raw
    if not isinstance(items, list):
        raise BadRequest("invalid_input", "input must be a string or a list of items", "input")
    messages, unlabeled = items_to_messages(items)
    instructions = body.get("instructions")
    if instructions is not None and not isinstance(instructions, str):
        raise BadRequest("invalid_input", "instructions must be a string", "instructions")
    if instructions:
        messages.insert(0, {"role": "system", "content": instructions})
    if not messages:
        raise BadRequest("invalid_input", "input is required", "input")

    fields: dict = {"store": False}
    for name in ("temperature", "top_p", "parallel_tool_calls"):
        if body.get(name) is not None:
            fields[name] = body[name]
    if body.get("max_output_tokens") is not None:
        fields["max_completion_tokens"] = body["max_output_tokens"]
    tools, kinds = _tools(body.get("tools") or [])
    if tools:
        fields["tools"] = tools
        if body.get("tool_choice") is not None:
            fields["tool_choice"] = _tool_choice(body["tool_choice"])
    text_format = (body.get("text") or {}).get("format")
    if text_format:
        fields["response_format"] = _response_format(text_format)
    effort = (body.get("reasoning") or {}).get("effort")
    if effort and effort != "none":      # Muse Spark answers 400 to "none"
        fields["reasoning_effort"] = effort
    return ChatRequest(messages, fields, "; ".join(unlabeled) or None, kinds)


# ---- output ---------------------------------------------------------------------------------------

def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def text_item(text: str, item_id: str | None = None) -> dict:
    return {"type": "message", "id": item_id or _id("msg"), "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def tool_item(call: dict, kinds: dict[str, str], item_id: str | None = None) -> dict:
    fn = call.get("function") or {}
    name, args, call_id = fn.get("name") or "", fn.get("arguments") or "", call.get("id") or _id("call")
    parsed = _json_object(args)
    if kinds.get(name) == "custom":
        value = parsed.get("input", args)
        return {"type": "custom_tool_call", "id": item_id or _id("ctc"), "status": "completed", "call_id": call_id,
                "name": name, "input": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}
    if kinds.get(name) == "local_shell":
        action = {"type": "exec", "command": parsed.get("command") or [], "env": {}}
        for src, dst in (("workdir", "working_directory"), ("timeout_ms", "timeout_ms")):
            if parsed.get(src) is not None:
                action[dst] = parsed[src]
        return {"type": "local_shell_call", "id": item_id or _id("lsh"), "status": "completed", "call_id": call_id,
                "action": action}
    return {"type": "function_call", "id": item_id or _id("fc"), "status": "completed", "call_id": call_id,
            "name": name, "arguments": args}


def _json_object(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def output_items(message: dict, kinds: dict[str, str]) -> list[dict]:
    items = [text_item(message["content"])] if isinstance(message.get("content"), str) and message["content"] else []
    return items + [tool_item(call, kinds) for call in message.get("tool_calls") or []]


def reply_messages(items: list[dict]) -> list[dict]:
    """The messages these items become when the client sends them back: what provenance must recognize.

    A client decides how it replays parallel calls (together, or each followed by its output), so every
    contiguous run of items is recorded. All of it is text the gateway generated.
    """
    out: list[dict] = []
    for start in range(len(items)):
        for end in range(start + 1, len(items) + 1):
            out += items_to_messages(items[start:end])[0]
    return out


def usage_block(usage: dict | None) -> dict | None:
    if not usage:
        return None
    details = usage.get("completion_tokens_details") or {}
    prompt, completion = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
    return {"input_tokens": prompt,
            "input_tokens_details": {"cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                                     or usage.get("cached_tokens") or 0},
            "output_tokens": completion,
            "output_tokens_details": {"reasoning_tokens": details.get("reasoning_tokens") or 0},
            "total_tokens": usage.get("total_tokens") or prompt + completion}


def _status(finish_reason: str | None) -> tuple[str, dict | None]:
    if finish_reason == "length":
        return "incomplete", {"reason": "max_output_tokens"}
    if finish_reason == "content_filter":
        return "incomplete", {"reason": "content_filter"}
    return "completed", None


def envelope(response_id: str, created: int, model: str, body: dict, *, status: str, output: list[dict],
             usage: dict | None = None, error: dict | None = None, incomplete: dict | None = None) -> dict:
    return {"id": response_id, "object": "response", "created_at": created, "status": status, "error": error,
            "incomplete_details": incomplete, "instructions": body.get("instructions"),
            "max_output_tokens": body.get("max_output_tokens"), "model": model, "output": output,
            "parallel_tool_calls": body.get("parallel_tool_calls", True), "previous_response_id": None,
            "reasoning": body.get("reasoning"), "store": False, "temperature": body.get("temperature"),
            "text": body.get("text"), "tool_choice": body.get("tool_choice", "auto"), "tools": body.get("tools") or [],
            "top_p": body.get("top_p"), "truncation": "disabled", "usage": usage_block(usage),
            "metadata": body.get("metadata") or {}}


def complete_response(data: dict, model: str, body: dict, kinds: dict[str, str]) -> tuple[dict, list[dict]]:
    """A restored chat completion as a Response, and the messages to record as provenance."""
    choice = (data.get("choices") or [{}])[0]
    items = output_items(choice.get("message") or {}, kinds)
    status, incomplete = _status(choice.get("finish_reason"))
    return (envelope(_id("resp"), int(time.time()), model, body, status=status, output=items,
                     usage=data.get("usage"), incomplete=incomplete), reply_messages(items))


class ResponsesRenderer:
    """Turns the restored chat chunks of one stream into Responses events."""

    def __init__(self, model: str, body: dict, kinds: dict[str, str]) -> None:
        self.model, self.body, self.kinds = model, body, kinds
        self.id, self.created, self.sequence = _id("resp"), int(time.time()), 0
        self.next_index = 0
        self.text: tuple[str, int] | None = None     # (item id, output_index) of the open message
        self.calls: dict[int, dict] = {}             # chat tool index -> id, output_index, opened
        self.items: list[dict] = []
        self.status, self.incomplete = "completed", None

    def _event(self, kind: str, **data) -> bytes:
        payload = {"type": kind, "sequence_number": self.sequence, **data}
        self.sequence += 1
        return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    def _envelope(self, status: str, **extra) -> dict:
        return envelope(self.id, self.created, self.model, self.body, status=status, **{"output": [], **extra})

    def start(self) -> list[bytes]:
        return [self._event("response.created", response=self._envelope("in_progress")),
                self._event("response.in_progress", response=self._envelope("in_progress"))]

    def _open_index(self) -> int:
        self.next_index += 1
        return self.next_index - 1

    def _text_delta(self, text: str) -> list[bytes]:
        out = []
        if self.text is None:
            self.text = (_id("msg"), self._open_index())
            item_id, index = self.text
            item = {"type": "message", "id": item_id, "status": "in_progress", "role": "assistant", "content": []}
            out.append(self._event("response.output_item.added", output_index=index, item=item))
            out.append(self._event("response.content_part.added", item_id=item_id, output_index=index, content_index=0,
                                   part={"type": "output_text", "text": "", "annotations": []}))
        item_id, index = self.text
        out.append(self._event("response.output_text.delta", item_id=item_id, output_index=index, content_index=0,
                               delta=text, logprobs=[]))
        return out

    def _call_delta(self, part: dict) -> list[bytes]:
        state = self.calls.setdefault(part.get("index", 0), {"id": _id("fc"), "output_index": None, "held": [],
                                                             "name": "", "call_id": None})
        fn = part.get("function") or {}
        state["name"] = state["name"] or fn.get("name") or ""
        state["call_id"] = state["call_id"] or part.get("id")
        if self.kinds.get(state["name"]):       # the whole input is known only at the end (see replies)
            return []
        if fn.get("arguments"):
            state["held"].append(fn["arguments"])
        if state["output_index"] is None:
            if not state["name"]:
                return []
            state["output_index"] = self._open_index()
            state["call_id"] = state["call_id"] or _id("call")
            item = {"type": "function_call", "id": state["id"], "status": "in_progress",
                    "call_id": state["call_id"], "name": state["name"], "arguments": ""}
            out = [self._event("response.output_item.added", output_index=state["output_index"], item=item)]
        else:
            out = []
        for delta in state["held"]:
            out.append(self._event("response.function_call_arguments.delta", item_id=state["id"],
                                   output_index=state["output_index"], delta=delta))
        state["held"] = []
        return out

    def chunk(self, chunk: dict) -> list[bytes]:
        out = []
        for choice in chunk.get("choices") or []:
            if choice.get("index", 0) != 0:      # the Responses API has one output; `n` is not offered upstream
                continue
            delta = choice.get("delta") or {}
            if delta.get("content"):
                out += self._text_delta(delta["content"])
            for part in delta.get("tool_calls") or []:
                out += self._call_delta(part)
        return out

    def replies(self, assembler: Assembler) -> list[dict]:
        messages = assembler.messages()
        message = messages[0] if messages else {}
        self.status, self.incomplete = _status(assembler.finish_reason)
        self.closing: list[bytes] = []
        indexed: list[tuple[int, dict]] = []
        if self.text is not None:
            item_id, index = self.text
            text = message.get("content") or ""
            item = text_item(text, item_id)
            part = item["content"][0]
            self.closing += [
                self._event("response.output_text.done", item_id=item_id, output_index=index, content_index=0,
                            text=text, logprobs=[]),
                self._event("response.content_part.done", item_id=item_id, output_index=index, content_index=0, part=part),
                self._event("response.output_item.done", output_index=index, item=item)]
            indexed.append((index, item))
        for (_, state), call in zip(sorted(self.calls.items()), message.get("tool_calls") or []):
            call = {**call, "id": state["call_id"] or call.get("id")}
            state["call_id"] = call["id"] = call["id"] or _id("call")
            item = tool_item(call, self.kinds, None if self.kinds.get(state["name"]) else state["id"])
            if state["output_index"] is None:
                state["output_index"] = self._open_index()
                added = {**item, "status": "in_progress"}
                if item["type"] == "function_call":
                    added["arguments"] = ""
                self.closing.append(self._event("response.output_item.added", output_index=state["output_index"], item=added))
            index = state["output_index"]
            if item["type"] == "function_call":
                self.closing.append(self._event("response.function_call_arguments.done", item_id=item["id"],
                                                output_index=index, name=item["name"], arguments=item["arguments"]))
            elif item["type"] == "custom_tool_call":
                self.closing.append(self._event("response.custom_tool_call_input.done", item_id=item["id"],
                                                output_index=index, input=item["input"]))
            self.closing.append(self._event("response.output_item.done", output_index=index, item=item))
            indexed.append((index, item))
        self.items = [item for _, item in sorted(indexed, key=lambda pair: pair[0])]
        return reply_messages(self.items)

    def finish(self, usage: dict | None, row: dict) -> list[bytes]:
        kind = "response.incomplete" if self.status == "incomplete" else "response.completed"
        return [*self.closing, sse_comment(cost_comment(row)),
                self._event(kind, response=self._envelope(self.status, output=self.items, usage=usage,
                                                          incomplete=self.incomplete))]

    def failed(self, code: str, message: str) -> list[bytes]:
        return [self._event("response.failed", response=self._envelope("failed", error={"code": code, "message": message}))]
