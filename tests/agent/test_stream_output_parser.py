import pytest

from omnibox.wizard.grimoire.agent.stream_parser import StreamParser, DeltaOperation

test_cases = [
    ["<think>\n", "当前", "情", "况应该调用工", "具 private", "_search\n<", "/", "think", ">\n我将调", "用工具：\n<t",
     "ool_", "call>\n", "{\"name\":", " \"private", "_search", "\",", " \"argum", "ents\": {\"", "query\": ", "\"小红",
     "\"}}\n</too", "l_", "c", "all>\n调用", "工具结束后", "，我将处理结果。"],
    ["<thi", "nk>\n当前情况", "应该调用工具 pri", "vate_sea", "rch\n", "</thi", "nk>\n我将调用工具", "：\n<", "tool_",
     "call>\n{\"", "name", "\": \"pr", "ivate_se", "arch\", \"", "argum", "en", "ts", "\": {\"query",
     "\": \"小红\"}}\n", "</tool_ca", "ll>", "\n调用工具结束后，我", "将处理结果", "。"],
    ["<t", "hink>\n", "当前情况应该调用", "工具 pri", "va", "te_se", "arch\n<", "/th", "i", "nk>\n我将调用",
     "工具：\n<to", "ol_", "cal", "l>\n{", "\"name\": ", "\"private_s", "earc", "h\", \"a", "rguments\"", ": {\"quer",
     "y\"", ": \"小红\"}", "}\n", "</too", "l_", "call>\n调用工具", "结束后，我", "将处理结果。"],
    ["<think>", "\n", "当前情况应该调用", "工具 pri", "va", "te_se", "arch", "\n", "</think>", "\n我将调用",
     "工具：\n", "<tool_call>", "\n{", "\"name\": ", "\"private_s", "earc", "h\", \"a", "rguments\"", ": {\"quer",
     "y\"", ": \"小红\"}", "}\n", "</too", "l_", "call>\n调用工具", "结束后，我", "将处理结果。"]
]

expected_message = {
    'think': '\n当前情况应该调用工具 private_search\n',
    'content': '\n我将调用工具：\n\n调用工具结束后，我将处理结果。',
    'tool_call': '\n{"name": "private_search", "arguments": {"query": "小红"}}\n'
}


@pytest.mark.parametrize("tokens", test_cases)
def test_stream_output_parser(tokens: list[str]):
    parser = StreamParser()
    message = {
        'content': '',
        'tool_call': '',
        'think': '',
    }
    for token in tokens:
        operations: list[DeltaOperation] = parser.parse(token)
        for op in operations:
            message[op['type']] += op['delta']
    for key in message.keys():
        assert message[key] == expected_message[key]
