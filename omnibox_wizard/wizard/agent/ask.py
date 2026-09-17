import os

from common.trace_info import TraceInfo
from omnibox_wizard.wizard.agent.backend_visible_client import (
    BackendVisibleBaseClient,
    BackendVisibleClient,
)
from omnibox_wizard.wizard.agent.resource_search import ResourceSearch
from wizard_common.grimoire.agent.ask import Ask as BasicAsk
from wizard_common.grimoire.agent.tool_executor import ToolExecutor
from wizard_common.grimoire.config import GrimoireAgentConfig
from wizard_common.grimoire.entity.api import ChatRequestOptions
from wizard_common.grimoire.entity.tools import BaseTool, ToolExecutorConfig
from wizard_common.grimoire.retriever.reranker import get_tool_executor_config


class Ask(BasicAsk):
    def __init__(
        self,
        config: GrimoireAgentConfig,
        backend_base_url: str | None = None,
    ):
        super().__init__(config=config)
        self.backend_base_url = (
            backend_base_url
            if backend_base_url is not None
            else os.getenv("OBW_BACKEND_BASE_URL")
        )
        self.knowledge_database_retriever = ResourceSearch(config=config.vector)
        self.retriever_mapping[self.knowledge_database_retriever.name] = (
            self.knowledge_database_retriever
        )

    def _visible_client(
        self, options: ChatRequestOptions, tool: BaseTool
    ) -> BackendVisibleBaseClient | None:
        user_id = getattr(options, "user_id", None)
        share_id = getattr(options, "share_id", None)
        if share_id and not user_id:
            return BackendVisibleBaseClient()
        namespace_id = getattr(tool, "namespace_id", None) or getattr(
            options, "namespace_id", None
        )
        if not user_id or not namespace_id or not self.backend_base_url:
            return None
        return BackendVisibleClient(
            base_url=self.backend_base_url,
            user_id=user_id,
            namespace_id=namespace_id,
        )

    def get_tool_executor(
        self,
        options: ChatRequestOptions,
        trace_info: TraceInfo,
        wrap_reranker: bool = True,
    ) -> ToolExecutor:
        tool_executor_config_list: list[ToolExecutorConfig] = []
        for tool in options.tools or []:
            extra = {}
            if tool.name == "private_search":
                extra["backend_client"] = self._visible_client(options, tool)
            tool_executor_config_list.append(
                self.retriever_mapping[tool.name].get_tool_executor_config(
                    tool,
                    trace_info=trace_info.get_child(tool.name),
                    **extra,
                )
            )

        if options.merge_search:
            tool_executor_config_list = [
                get_tool_executor_config(tool_executor_config_list, self.reranker)
            ]
        elif wrap_reranker:
            for tool_executor_config in tool_executor_config_list:
                tool_executor_config["func"] = self.reranker.wrap(
                    func=tool_executor_config["func"],
                    trace_info=trace_info.get_child("reranker"),
                )

        tool_executor_config: dict = {c["name"]: c for c in tool_executor_config_list}
        return ToolExecutor(tool_executor_config)
