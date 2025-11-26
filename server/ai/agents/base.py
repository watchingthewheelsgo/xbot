from abc import ABC
from pydantic import BaseModel


class BaseAgent(BaseModel, ABC):
    def __init__(self):
        pass


class ReActAgent(BaseAgent):
    def __init__(self):
        pass


class ToolCallAgent(ReActAgent):
    def __init__(self):
        pass


class Agent(ToolCallAgent):
    def __init__(self):
        pass
