import json
import logging
import re
from typing import Any, Dict, List, Set
from pydantic import BaseModel, Field
from typing_extensions import Literal

from src.agent.prompts import get_prompt
from src.agent.assistant import get_default_llm

logger = logging.getLogger("mcp.orchestrator")


class SubTask(BaseModel):
    id: str = Field(..., description="ID duy nhất của tác vụ con (e.g., task_1)")
    name: str = Field(..., description="Tên ngắn gọn của tác vụ")
    description: str = Field(..., description="Mô tả chi tiết những việc cần làm và kết quả mong muốn")
    dependencies: List[str] = Field(default_factory=list, description="Danh sách các ID tác vụ cần hoàn thành trước")
    estimated_time: float = Field(default=10.0, description="Thời gian ước lượng chạy tác vụ tính bằng giây")
    priority: Literal["HIGH", "MEDIUM", "LOW"] = Field(default="MEDIUM", description="Độ ưu tiên")
    critical: bool = Field(default=False, description="Tác vụ cốt lõi, bắt buộc phải thành công")


class ExecutionPlan(BaseModel):
    analysis: str = Field(..., description="Phân tích yêu cầu và kế hoạch song song hóa")
    subtasks: List[SubTask] = Field(..., description="Danh sách các tác vụ con")
    total_estimated_time: float = Field(..., description="Tổng thời gian chạy tuần tự ước tính")
    execution_waves: List[List[str]] = Field(default_factory=list, description="Danh sách các wave chạy song song (được tính toán tự động)")


class TaskDecompositionEngine:
    """Engine chịu trách nhiệm phân rã yêu cầu lớn thành các tác vụ con có cấu trúc DAG."""

    def __init__(self, llm_client: Any = None, config: Dict[str, Any] = None):
        self.llm = llm_client or get_default_llm()
        self.config = config or {"max_subtasks": 15, "parallelization_threshold": 0.6}

    async def decompose_request(
        self, user_request: str, token_budget: int = 10000, time_limit: int = 120
    ) -> ExecutionPlan:
        """Phân rã yêu cầu của người dùng thành một kế hoạch thực thi (ExecutionPlan)."""
        prompt = get_prompt(
            "TASK_DECOMPOSITION_PROMPT",
            user_request=user_request,
            token_budget=token_budget,
            time_limit=time_limit,
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        plan = self._parse_json_response(content)
        self._validate_and_build_waves(plan)
        return plan

    def _parse_json_response(self, text: str) -> ExecutionPlan:
        """Parse và làm sạch dữ liệu JSON trả về từ LLM."""
        # Loại bỏ markdown codeblocks nếu có
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Lấy nội dung bên trong block ```json ... ``` hoặc ``` ... ```
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1).strip()

        try:
            data = json.loads(cleaned)
            return ExecutionPlan(**data)
        except Exception as e:
            # Dự phòng: Thử tìm JSON tiềm năng bằng regex nếu có text thừa xung quanh
            match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    return ExecutionPlan(**data)
                except Exception:
                    pass
            raise ValueError(f"Không thể parse JSON từ phản hồi của LLM. Lỗi: {e}. Phản hồi: {text}")

    def _validate_and_build_waves(self, plan: ExecutionPlan) -> None:
        """
        Kiểm tra tính hợp lệ của đồ thị DAG (không có chu trình, các dependency tồn tại)
        và phân chia danh sách tác vụ thành các wave (lớp chạy song song).
        """
        subtask_map = {task.id: task for task in plan.subtasks}
        
        # 1. Kiểm tra tính hợp lệ của các dependencies
        for task in plan.subtasks:
            for dep in task.dependencies:
                if dep not in subtask_map:
                    # Nếu dependency không tồn tại, tự động loại bỏ hoặc log warning
                    logger.warning("Task %s depends on non-existent task %s. Removing dependency.", task.id, dep)
                    task.dependencies.remove(dep)

        # 2. Xây dựng các wave thực thi (Topological Sort dựa trên độ sâu phụ thuộc)
        completed: Set[str] = set()
        remaining = list(plan.subtasks)
        waves: List[List[str]] = []

        limit_loop = 100  # Chống lặp vô hạn
        while remaining and limit_loop > 0:
            limit_loop -= 1
            current_wave: List[str] = []
            
            # Tìm tất cả các task có các dependency đã hoàn thành
            for task in list(remaining):
                # Các dependency phải nằm trong tập completed
                if all(dep in completed for dep in task.dependencies):
                    current_wave.append(task.id)
                    remaining.remove(task)
            
            if not current_wave:
                # Nếu còn task nhưng không task nào chạy được, nghĩa là có chu trình phụ thuộc!
                circular_tasks = [task.id for task in remaining]
                raise ValueError(
                    f"Phát hiện chu trình phụ thuộc (Circular Dependency) trong các tác vụ: {circular_tasks}"
                )
            
            waves.append(current_wave)
            completed.update(current_wave)

        if remaining:
            raise ValueError("Không thể phân rã hoàn toàn toàn bộ tác vụ do lỗi đồ thị phụ thuộc.")

        plan.execution_waves = waves
