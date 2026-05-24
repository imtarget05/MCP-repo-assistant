import unittest

from langchain_core.messages import AIMessage, HumanMessage

from src.agent.assistant import build_app


class FakeLLM:
    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages, **kwargs):
        return AIMessage(content="This is a long, valid response from the fake LLM to satisfy verification.")


class TestAssistant(unittest.IsolatedAsyncioTestCase):
    async def test_workflow_compilation(self):
        app = build_app(llm=FakeLLM())
        self.assertIsNotNone(app)

    async def test_invoke_agent(self):
        app = build_app(llm=FakeLLM())
        from src.agent.assistant import AgentState
        inputs: AgentState = {"messages": [HumanMessage(content="Hello")], "is_valid": False, "retry_count": 0, "reasoning": ""}
        result = await app.ainvoke(inputs)
        self.assertEqual(result["messages"][-1].content, "This is a long, valid response from the fake LLM to satisfy verification.")


if __name__ == "__main__":
    unittest.main()