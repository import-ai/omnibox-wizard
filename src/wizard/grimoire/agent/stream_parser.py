from typing import TypedDict, Literal, List


class DeltaOperation(TypedDict):
    type: Literal['content', 'think', 'tool_call']
    delta: str


class StreamParser:
    def __init__(self):
        # Track the current tag context and buffer for incomplete tags
        self._current = "content"  # Default type
        self._buffer = ""
        self._tag_stack = []
        self._tag_map = {
            "think": "think",
            "tool_call": "tool_call",
        }

    def parse(self, token: str) -> List[DeltaOperation]:
        ops: List[DeltaOperation] = []
        text = self._buffer + token  # prepend any leftover from last call
        self._buffer = ""
        cursor = 0
        while cursor < len(text):
            # Find the next tag
            next_tag_start = text.find("<", cursor)
            if next_tag_start == -1:
                # No tag, all in current context
                if cursor < len(text):
                    ops.append({"type": self._current, "delta": text[cursor:]})
                break
            if next_tag_start > cursor:
                # Content before next tag
                ops.append({"type": self._current, "delta": text[cursor:next_tag_start]})
                cursor = next_tag_start

            # Now at a tag
            # Try to consume a tag fully, if not enough chars then buffer and break
            # Tags are of form <think>, </think>, <tool_call>, </tool_call>
            for tag in ["<think>", "</think>", "<tool_call>", "</tool_call>"]:
                tag_len = len(tag)
                if text.startswith(tag, cursor):
                    if tag[1] == "/":
                        # It's a closing tag
                        self._tag_stack.pop() if self._tag_stack else None
                        # After closing, revert to previous or default to 'content'
                        self._current = self._tag_stack[-1] if self._tag_stack else "content"
                    else:
                        # It's an opening tag
                        name = tag[1:-1]
                        mapped = self._tag_map[name]
                        self._tag_stack.append(mapped)
                        self._current = mapped
                    cursor += tag_len
                    break
            else:
                # Tag is incomplete, buffer and break
                self._buffer = text[cursor:]
                break
        return [op for op in ops if op["delta"]]
