import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agent.task_orchestrator import TaskDecompositionEngine, ExecutionPlan, SubTask
from src.agent.parallel_executor import ParallelExecutor, ExecutionStrategy


class FakeLLM:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.ainvoke = AsyncMock()
        
        # Thiết lập return value cho ainvoke
        mock_response = MagicMock()
        mock_response.content = response_text
        self.ainvoke.return_value = mock_response


@pytest.mark.asyncio
async def test_task_decomposition_waves():
    # Mock LLM response với cấu trúc JSON hoàn chỉnh của ExecutionPlan
    mock_json = """
    {
      "analysis": "Test phân tách tác vụ phức tạp.",
      "subtasks": [
        {"id": "task_1", "name": "Task 1", "description": "Lấy thông tin", "dependencies": [], "estimated_time": 5.0, "priority": "HIGH", "critical": true},
        {"id": "task_2", "name": "Task 2", "description": "Tải file", "dependencies": ["task_1"], "estimated_time": 10.0, "priority": "MEDIUM", "critical": false},
        {"id": "task_3", "name": "Task 3", "description": "Phân tích bảo mật", "dependencies": ["task_1"], "estimated_time": 15.0, "priority": "HIGH", "critical": true},
        {"id": "task_4", "name": "Task 4", "description": "Tổng hợp kết quả", "dependencies": ["task_2", "task_3"], "estimated_time": 5.0, "priority": "MEDIUM", "critical": true}
      ],
      "total_estimated_time": 35.0
    }
    """
    fake_llm = FakeLLM(mock_json)
    engine = TaskDecompositionEngine(llm_client=fake_llm)

    plan = await engine.decompose_request("Test request")
    
    assert plan.analysis == "Test phân tách tác vụ phức tạp."
    assert len(plan.subtasks) == 4
    assert plan.total_estimated_time == 35.0
    
    # Kiểm tra thuật toán Topological Sort phân wave
    # Wave 0 phải là task_1 (không có dependency)
    assert plan.execution_waves[0] == ["task_1"]
    # Wave 1 phải là task_2 và task_3 (phụ thuộc task_1)
    assert set(plan.execution_waves[1]) == {"task_2", "task_3"}
    # Wave 2 phải là task_4 (phụ thuộc task_2, task_3)
    assert plan.execution_waves[2] == ["task_4"]


@pytest.mark.asyncio
async def test_circular_dependency_error():
    # Đồ thị phụ thuộc vòng tròn: task_1 -> task_2 -> task_1
    mock_json = """
    {
      "analysis": "Đồ thị lỗi vòng tròn.",
      "subtasks": [
        {"id": "task_1", "name": "Task 1", "description": "Lỗi", "dependencies": ["task_2"], "estimated_time": 5.0},
        {"id": "task_2", "name": "Task 2", "description": "Lỗi", "dependencies": ["task_1"], "estimated_time": 5.0}
      ],
      "total_estimated_time": 10.0
    }
    """
    fake_llm = FakeLLM(mock_json)
    engine = TaskDecompositionEngine(llm_client=fake_llm)

    # Phải ném ngoại lệ ValueError do chu trình phụ thuộc
    with pytest.raises(ValueError) as excinfo:
        await engine.decompose_request("Test request")
    assert "circular dependency" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_parallel_executor_success():
    # Chuẩn bị Kế hoạch thực thi mẫu
    plan = ExecutionPlan(
        analysis="Thử nghiệm chạy song song.",
        subtasks=[
            SubTask(id="task_1", name="Task 1", description="Chạy 1", dependencies=[], estimated_time=5.0),
            SubTask(id="task_2", name="Task 2", description="Chạy 2", dependencies=["task_1"], estimated_time=5.0)
        ],
        total_estimated_time=10.0,
        execution_waves=[["task_1"], ["task_2"]]
    )

    # Mock LLM cho Aggregator và Recovery
    fake_llm = FakeLLM("Báo cáo tổng hợp kết quả hoàn thành xuất sắc.")
    executor = ParallelExecutor(
        max_concurrent_tasks=2,
        execution_strategy=ExecutionStrategy.SPEED_FIRST,
        llm_client=fake_llm
    )

    # Hàm mock thực thi task con
    async def mock_execute_func(task_id, subtask_def, dependencies_outputs):
        return f"Kết quả thành công từ {task_id}"

    # Trình lắng nghe status callback
    status_events = []
    async def status_callback(event):
        status_events.append(event)

    results = await executor.execute_workflow(
        execution_plan=plan,
        execution_func=mock_execute_func,
        status_callback=status_callback,
        context={"user_request": "Chạy thử nghiệm song song"}
    )

    # Đảm bảo hoàn thành và tổng hợp đúng
    assert results["final_answer"] == "Báo cáo tổng hợp kết quả hoàn thành xuất sắc."
    assert results["task_statuses"]["task_1"] == "COMPLETED"
    assert results["task_statuses"]["task_2"] == "COMPLETED"
    assert results["task_outputs"]["task_1"] == "Kết quả thành công từ task_1"
    
    # Kiểm tra metrics
    metrics = results["metrics"]
    assert metrics["total_tasks"] == 2
    assert metrics["completed_tasks"] == 2
    assert metrics["failed_tasks"] == 0
    
    # Kiểm tra các sự kiện SSE được kích hoạt đúng
    events = [e["event"] for e in status_events]
    assert "wave_start" in events
    assert "task_start" in events
    assert "task_complete" in events
    assert "wave_complete" in events
    assert "aggregating" in events
