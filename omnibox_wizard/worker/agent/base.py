import json as jsonlib
import re
from typing import Type, TypeVar, Generic, AsyncIterator

from jinja2 import Template
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from opentelemetry import propagate
from pydantic import BaseModel

from common import project_root
from common.template_parser import TemplateParser
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import OpenAIConfig

InputType = TypeVar("InputType", bound=BaseModel)
OutputType = TypeVar("OutputType")


def md_json_dumps(data: dict | list | BaseModel) -> str:
    if isinstance(data, BaseModel):
        data = data.model_dump(exclude_none=True)
    return "\n".join(["```json", jsonlib.dumps(data, ensure_ascii=False, separators=(",", ":")), "```"])


def get_openapi_schema(schema_name: Type[BaseModel]) -> dict:
    json_schema: dict = schema_name.model_json_schema()

    properties: dict = json_schema["properties"]
    keys: list[str] = list(properties.keys())
    for k in keys:
        v = properties[k]
        if v["title"].replace(" ", "_").lower() == k:
            v.pop("title")
        for excluded_key in ["default"]:
            if excluded_key in v:
                v.pop(excluded_key)
    return json_schema


class JSONParser:
    _json_markdown_re = re.compile(r"```json(.*)", re.DOTALL)
    _json_strip_chars = " \n\r\t`"

    @classmethod
    def valid(cls, text: str) -> str | None:
        striped_text: str = text.strip(cls._json_strip_chars)
        for ch in ["{}", "[]"]:
            if striped_text.startswith(ch[0]) and striped_text.endswith(ch[1]):
                return striped_text
        return None

    @classmethod
    def parse(cls, text: str, trace_info: TraceInfo | None = None) -> dict | list:
        if (match := cls._json_markdown_re.search(text)) is not None:
            json_string: str = match.group(1)
            json_string: str = json_string.strip(cls._json_strip_chars)

            json_response: dict = jsonlib.loads(json_string)
        elif json_string := cls.valid(text):
            json_response: dict = jsonlib.loads(json_string)
        else:
            trace_info and trace_info.error({
                "text": text,
                "message": "The provided text does not contain valid JSON.",
            })
            raise ValueError("The provided text does not contain valid JSON.")
        return json_response


ExamplesType = list[tuple[dict | list, dict | list | str]] | None


class BaseAgent(Generic[InputType, OutputType]):
    template_parser = TemplateParser(base_dir=project_root.path("omnibox_wizard/resources/prompt_templates"))

    @classmethod
    def get_template(cls, template: str | Template) -> Template | None:
        return cls.template_parser.get_template(template) if isinstance(template, str) else template

    def __init__(
            self,
            openai_config: OpenAIConfig,
            input_class: Type[InputType],
            output_class: Type[OutputType],
            *,
            system_prompt_template: Template | str,
            user_prompt_template: Template | str | None = None,
            examples: ExamplesType = None
    ):
        self.input_class: Type[InputType] = input_class
        self.output_class: Type[OutputType] = output_class

        self.system_prompt_template: Template = self.get_template(system_prompt_template)

        self.user_prompt_template: Template | None = self.get_template(
            user_prompt_template) if user_prompt_template else None

        self.examples: list[tuple[str, str]] = [
            (
                self.render_user_prompt(i),
                self.parse_output(o) if issubclass(self.output_class, str) else md_json_dumps(self.parse_output(o))
            )
            for i, o in examples or []
        ]

        self.openai_config: OpenAIConfig = openai_config

    def render_system_prompt(self, context: InputType) -> str:
        output_format: str = "\n\n".join(
            [
                "# Output Format",
                "You must respond with valid JSON that strictly follows the OpenAPI schema provided below. Do not include any additional text, explanations, or formatting outside of the JSON response.",
                md_json_dumps(get_openapi_schema(self.output_class))
            ] if issubclass(self.output_class, BaseModel) else []
        )
        system_prompt: str = self.template_parser.render_template(
            self.system_prompt_template,
            lang=getattr(context, "lang", None) or "简体中文",
            output_format=output_format,
            **context.model_dump()
        )

        if output_format and output_format not in system_prompt:
            return "\n\n".join([system_prompt, output_format])
        return system_prompt

    def render_user_prompt(self, context: dict | InputType) -> str:
        if isinstance(context, dict):
            context = self.input_class.model_validate(context)
        json_context: dict = context.model_dump(exclude_none=True)
        if self.user_prompt_template:
            return self.template_parser.render_template(self.user_prompt_template, **json_context)
        else:
            return md_json_dumps(json_context)

    def prepare_context(self, context: dict | InputType) -> InputType:
        if not isinstance(context, self.input_class):
            context = self.input_class.model_validate(context)
        return context

    def prepare_messages(self, context: InputType) -> list[dict[str, str]]:
        system_prompt: str = self.render_system_prompt(context)
        user_prompt: str = self.render_user_prompt(context)
        return [
            {"role": "system", "content": system_prompt},
            *sum([[{"role": "user", "content": example[0]}, {"role": "assistant", "content": example[1]}]
                  for example in self.examples], []),
            {"role": "user", "content": user_prompt}
        ]

    def parse_output(self, output: str | dict | list | OutputType, trace_info: TraceInfo | None = None) -> OutputType:
        if isinstance(output, self.output_class):
            return output
        if isinstance(output, str):
            str_output: str = output.strip()
        elif isinstance(output, (dict, list)):
            str_output: str = jsonlib.dumps(output, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(output, BaseModel):
            str_output: str = output.model_dump_json(exclude_none=True)
        else:
            raise TypeError(
                f"Output must be a string, dict, list, or an instance of {self.output_class}, got {type(output)}")

        if issubclass(self.output_class, BaseModel):
            json_response: dict | list = JSONParser.parse(str_output, trace_info=trace_info)
            return self.output_class.model_validate(json_response)
        if issubclass(self.output_class, str):
            return self.output_class(str_output)
        raise TypeError(f"Output class {self.output_class} is not a valid BaseModel or str subclass.")

    async def ainvoke(self, context: dict | InputType, trace_info: TraceInfo | None = None) -> OutputType:
        str_response: str = ''
        async for delta in self.astream(context, trace_info):
            str_response += delta
        response = self.parse_output(str_response, trace_info=trace_info)
        return response

    async def astream(self, context: dict | InputType, trace_info: TraceInfo) -> AsyncIterator[str]:
        response: str = ''
        messages: list[dict[str, str]] = self.prepare_messages(self.prepare_context(context))
        headers = {}
        propagate.inject(headers)
        if trace_info:
            headers = headers | {"X-Request-Id": trace_info.request_id}
        openai_async_stream_response: AsyncStream[ChatCompletionChunk] = await self.openai_config.chat(
            messages=messages,
            stream=True,
            extra_headers=headers if headers else None,
        )
        async for chunk in openai_async_stream_response:
            if delta := chunk.choices[0].delta.content:
                response += delta
                yield delta
        trace_info.debug({
            "context": context if isinstance(context, dict) else context.model_dump(),
            "messages": messages,
            "response": response,
        })

    @classmethod
    def create_agent(
            cls, openai_config: OpenAIConfig, input_class: Type[InputType], output_class: Type[OutputType], *,
            system_prompt_template: Template | str, examples: ExamplesType = None
    ) -> "BaseAgent[InputType, OutputType]":
        return cls(
            openai_config, input_class, output_class,
            system_prompt_template=system_prompt_template,
            examples=examples,
        )
