import os
from functools import lru_cache
from typing import Annotated, Sequence
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END, add_messages
from langgraph.prebuilt import ToolNode

from src.agent.tools import repo_assistant_tools

load_dotenv()

# Define the state for the graph
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    reasoning: str
    is_valid: bool
    retry_count: int

def get_langfuse_callback():
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse.callback import CallbackHandler # type: ignore
            return [CallbackHandler(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
            )]
        except Exception as e:
            print(f"⚠️ Failed to initialize Langfuse callback: {e}")
    return []

def get_default_llm():
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
    return ChatOpenAI(model=model_name, temperature=0, streaming=True)


def build_app(llm=None, tools=None):
    active_llm = llm or get_default_llm()
    active_tools = tools or repo_assistant_tools
    llm_with_tools = active_llm.bind_tools(active_tools)

    async def tool_calling_agent(state: AgentState):
        messages = state["messages"]
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    async def verify_response(state: AgentState):
        # Intelligent verification: check for empty, too short, errors, or placeholder responses
        messages = state["messages"]
        last_message = messages[-1]
        retry_count = state.get("retry_count", 0)
        
        if not isinstance(last_message, AIMessage) or not last_message.content:
            feedback = "The response is empty or is not a valid AI message. Please provide a complete response."
            return {
                "is_valid": False,
                "retry_count": retry_count + 1,
                "messages": [HumanMessage(content=f"[Validation Failed]: {feedback} Please correct this.")]
            }
            
        content = last_message.content
        if isinstance(content, list):
            text_content = ""
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_content += block.get("text", "")
                elif isinstance(block, str):
                    text_content += block
            content = text_content
        elif not isinstance(content, str):
            content = str(content)
        
        # Check 1: Too short
        if len(content.strip()) < 10:
            feedback = "The response is extremely brief. Please provide a more detailed and helpful answer with proper context."
            return {
                "is_valid": False,
                "retry_count": retry_count + 1,
                "messages": [HumanMessage(content=f"[Validation Failed]: {feedback} Please expand your response.")]
            }
            
        # Check 2: Contains unresolved tool error
        if "Error fetching" in content or "Error reading file" in content or "Error searching repo" in content or ("error" in content.lower() and ("failed" in content.lower() or "exception" in content.lower())):
            feedback = "The response contains a tool execution error. Please try a different tool, check the repository structure, or explain the error gracefully instead of just repeating it."
            return {
                "is_valid": False,
                "retry_count": retry_count + 1,
                "messages": [HumanMessage(content=f"[Validation Failed]: {feedback} Please self-correct and try an alternative approach.")]
            }
            
        # Check 3: Placeholders
        if "TODO" in content or "placeholder" in content.lower() or "insert code here" in content.lower():
            feedback = "The response contains placeholder comments like 'TODO' or 'insert code here'. Please provide a complete, working explanation or code implementation."
            return {
                "is_valid": False,
                "retry_count": retry_count + 1,
                "messages": [HumanMessage(content=f"[Validation Failed]: {feedback} Replace all placeholders with actual details.")]
            }
            
        return {"is_valid": True}

    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        
        if getattr(last_message, "tool_calls", None):
            return "tools"
            
        return "verifier"

    def after_verification(state: AgentState):
        if state.get("is_valid") or state.get("retry_count", 0) >= 3:
            return END
        return "agent"

    workflow = StateGraph(AgentState)  # type: ignore[arg-type]
    workflow.add_node("agent", tool_calling_agent)
    workflow.add_node("tools", ToolNode(active_tools))
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


@lru_cache(maxsize=1)
def get_app():
    return build_app()


async def invoke_agent(user_input: str, app_instance=None):
    graph = app_instance or get_app()
    callbacks = get_langfuse_callback()
    from typing import Any
    config: Any = {"callbacks": callbacks} if callbacks else None
    inputs: AgentState = {"messages": [HumanMessage(content=user_input)], "is_valid": False, "retry_count": 0, "reasoning": ""}
    result = await graph.ainvoke(
        inputs,
        config=config
    )
    final_message = result["messages"][-1]
    if isinstance(final_message, AIMessage):
        return final_message.content
    return str(getattr(final_message, "content", final_message))


app = None

async def main():
    print("🚀 GitHub Repo Assistant (LangGraph + MCP)")
    print("Type 'exit' to quit.")
    
    app = get_app()
    
    while True:
        try:
            user_input = input("\n👤 You: ")
            if user_input.lower() in ["exit", "quit"]:
                break
                
            inputs: AgentState = {"messages": [HumanMessage(content=user_input)], "is_valid": False, "retry_count": 0, "reasoning": ""}
            callbacks = get_langfuse_callback()
            from typing import Any
            config: Any = {"callbacks": callbacks} if callbacks else None
            
            async for output in app.astream(inputs, stream_mode="updates", config=config):
                for node, data in output.items():
                    if node == "agent":
                        message = data["messages"][-1]
                        if message.tool_calls:
                            for tool_call in message.tool_calls:
                                print(f"🛠️  Using tool: {tool_call['name']}...")
                        elif message.content:
                            print(f"\n🤖 Assistant: {message.content}")
                    elif node == "verifier":
                        if not data.get("is_valid"):
                            print("⚠️  Response quality check failed, retrying...")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
