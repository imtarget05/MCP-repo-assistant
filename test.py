from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, add_messages

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    reasoning: str
    is_valid: bool
    retry_count: int

try:
    sg = StateGraph(AgentState)
    print("Success:", sg)
except Exception as e:
    import traceback
    traceback.print_exc()
