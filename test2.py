import os
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END, add_messages
from langgraph.prebuilt import ToolNode

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    reasoning: str
    is_valid: bool
    retry_count: int

def build_app():
    async def tool_calling_agent(state: AgentState):
        pass

    async def verify_response(state: AgentState):
        pass

    def should_continue(state: AgentState):
        return "verifier"

    def after_verification(state: AgentState):
        return END

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", tool_calling_agent)
    # Mocking ToolNode with an empty list of tools since we don't need real tools
    workflow.add_node("tools", ToolNode([]))
    workflow.add_node("verifier", verify_response)

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "verifier": "verifier",
        },
    )
    workflow.add_edge("tools", "agent")
    workflow.add_conditional_edges(
        "verifier",
        after_verification,
        {
            "agent": "agent",
            END: END,
        },
    )
    
    return workflow.compile()

try:
    app = build_app()
    print("Success compile:", app)
except Exception as e:
    import traceback
    traceback.print_exc()
