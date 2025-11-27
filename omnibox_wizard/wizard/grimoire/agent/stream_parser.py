from typing import TypedDict, List


class DeltaOperation(TypedDict):
    tag: str
    delta: str


class StreamParser:
    def __init__(self, tags: List[str] | None = None, default: str = "content"):
        # Track the current tag context and buffer for incomplete tags
        self._default: str = default
        self._current: str = self._default  # Default type
        self._buffer = ""
        self._tag_stack = []

        self._tags = sum(
            [[f"<{tag}>", f"</{tag}>"] for tag in tags or ["think", "tool_call"]], []
        )

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
                    ops.append({"tag": self._current, "delta": text[cursor:]})
                break
            if next_tag_start > cursor:
                # Content before next tag
                ops.append({"tag": self._current, "delta": text[cursor:next_tag_start]})
                cursor = next_tag_start

            # Now at a tag
            # Try to consume a tag fully, if not enough chars then buffer and break
            for tag in self._tags:
                tag_len = len(tag)
                if text.startswith(tag, cursor):
                    if tag[1] == "/":
                        # It's a closing tag
                        self._tag_stack.pop() if self._tag_stack else None
                        # After closing, revert to previous or default to self._default
                        self._current = (
                            self._tag_stack[-1] if self._tag_stack else self._default
                        )
                    else:
                        # It's an opening tag
                        name = tag[1:-1]
                        self._tag_stack.append(name)
                        self._current = name
                    cursor += tag_len
                    break
            else:
                # Tag is incomplete, buffer and break
                self._buffer = text[cursor:]
                break
        return [op for op in ops if op["delta"]]
