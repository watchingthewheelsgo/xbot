from abc import ABC

from pydantic import BaseModel, ConfigDict


class BaseAgent(BaseModel, ABC):
    model_config = ConfigDict(extra="allow")


class ReActAgent(BaseAgent):
    pass


class ToolCallAgent(ReActAgent):
    pass


class Agent(ToolCallAgent):
    pass
