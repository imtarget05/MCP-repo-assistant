import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel

from src.agent.prompts import get_prompt
from src.agent.task_orchestrator import ExecutionPlan, SubTask
from src.agent.assistant import get_default_llm

logger = logging.getLogger("mcp.executor")


class ExecutionStrategy(str, Enum):
    SPEED_FIRST = "SPEED_FIRST"
    QUALITY_FIRST = "QUALITY_FIRST"
    BALANCED = "BALANCED"


class ParallelExecutor:
    """Khung điều phối và thực thi song song các tác vụ con dựa trên DAG."""

    def __init__(
        self,
        max_concurrent_tasks: int = 5,
        execution_strategy: ExecutionStrategy = ExecutionStrategy.BALANCED,
        timeout_per_task: float = 30.0,
        llm_client: Any = None,
    ):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.strategy = execution_strategy
        self.timeout_per_task = timeout_per_task
        self.llm = llm_client or get_default_llm()
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async def execute_workflow(
        self,
        execution_plan: ExecutionPlan,
        execution_func: Callable[[str, SubTask, str], Any],
        status_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Thực thi toàn bộ kế hoạch (ExecutionPlan).
        
        Args:
            execution_plan: Kế hoạch thực thi gồm các wave và subtask.
            execution_func: Hàm callback để thực thi một task cụ thể.
                            Nhận vào: task_id, subtask_def, dependencies_outputs.
            status_callback: Hàm callback nhận thông tin cập nhật tiến độ (sự kiện, dữ liệu).
            context: Ngữ cảnh toàn cục bổ sung từ user request.
        """
        user_request = (context or {}).get("user_request", "Yêu cầu tổng quát của dự án")
        task_map = {task.id: task for task in execution_plan.subtasks}
        
        # Lưu trữ trạng thái và kết quả
        task_outputs: Dict[str, str] = {}
        task_statuses: Dict[str, str] = {task.id: "PENDING" for task in execution_plan.subtasks}
        task_errors: Dict[str, str] = {}
        wave_results: List[Dict[str, Any]] = []

        start_time = time.time()

        # Thực thi lần lượt từng wave (các task trong một wave chạy song song)
        for wave_idx, wave in enumerate(execution_plan.execution_waves):
            logger.info("Wave %d/%d started: %s", wave_idx + 1, len(execution_plan.execution_waves), wave)
            if status_callback:
                await status_callback({
                    "event": "wave_start",
                    "data": {
                        "wave_index": wave_idx,
                        "tasks": wave
                    }
                })
                
            wave_start = time.time()
            wave_tasks = []

            # Tạo coroutine cho từng task trong wave
            for task_id in wave:
                subtask_def = task_map[task_id]
                wave_tasks.append(
                    self._execute_single_task_with_retry_and_sem(
                        task_id=task_id,
                        subtask_def=subtask_def,
                        user_request=user_request,
                        task_outputs=task_outputs,
                        task_statuses=task_statuses,
                        task_errors=task_errors,
                        execution_func=execution_func,
                        status_callback=status_callback,
                    )
                )

            # Chạy song song tất cả các task trong wave hiện tại
            await asyncio.gather(*wave_tasks)
            
            wave_duration = time.time() - wave_start
            wave_results.append({
                "wave_index": wave_idx,
                "tasks": wave,
                "duration_seconds": wave_duration,
                "statuses": {tid: task_statuses[tid] for tid in wave}
            })
            
            if status_callback:
                await status_callback({
                    "event": "wave_complete",
                    "data": {
                        "wave_index": wave_idx,
                        "duration_seconds": wave_duration,
                        "statuses": {tid: task_statuses[tid] for tid in wave}
                    }
                })

            # Kiểm tra xem có task critical nào bị thất bại không
            for task_id in wave:
                if task_statuses[task_id] == "FAILED" and task_map[task_id].critical:
                    # Nếu là task critical thất bại, chúng ta dừng toàn bộ workflow
                    if self.strategy != ExecutionStrategy.SPEED_FIRST:
                        raise RuntimeError(
                            f"Workflow bị dừng do tác vụ quan trọng (critical) '{task_id}' thất bại: {task_errors.get(task_id)}"
                        )

        total_duration = time.time() - start_time
        
        # 1. Tổng hợp kết quả cuối cùng (Aggregation)
        logger.info("Aggregating results from all subtasks")
        if status_callback:
            await status_callback({
                "event": "aggregating",
                "data": {}
            })
            
        subtasks_results_str = "\n\n".join(
            f"=== [{task_id}] {task_map[task_id].name} ===\nTrạng thái: {task_statuses[task_id]}\nKết quả:\n{task_outputs.get(task_id, 'Không có kết quả.')}"
            for task_id in task_statuses
        )
        
        agg_prompt = get_prompt(
            "RESULT_AGGREGATION_PROMPT",
            user_request=user_request,
            subtasks_results=subtasks_results_str,
        )
        
        agg_response = await self.llm.ainvoke(agg_prompt)
        final_answer = agg_response.content if hasattr(agg_response, "content") else str(agg_response)

        # 2. Tính toán metrics
        serial_duration = sum(task_map[tid].estimated_time for tid in task_statuses)
        speedup = serial_duration / total_duration if total_duration > 0 else 1.0
        success_rate = sum(1 for status in task_statuses.values() if status == "COMPLETED") / len(task_statuses)

        metrics = {
            "parallel_duration_seconds": total_duration,
            "serial_duration_seconds": serial_duration,
            "speedup_factor": round(speedup, 2),
            "success_rate": round(success_rate, 2),
            "total_tasks": len(task_statuses),
            "completed_tasks": sum(1 for status in task_statuses.values() if status == "COMPLETED"),
            "failed_tasks": sum(1 for status in task_statuses.values() if status == "FAILED"),
        }

        return {
            "final_answer": final_answer,
            "task_outputs": task_outputs,
            "task_statuses": task_statuses,
            "task_errors": task_errors,
            "wave_results": wave_results,
            "metrics": metrics,
        }

    async def _execute_single_task_with_retry_and_sem(
        self,
        task_id: str,
        subtask_def: SubTask,
        user_request: str,
        task_outputs: Dict[str, str],
        task_statuses: Dict[str, str],
        task_errors: Dict[str, str],
        execution_func: Callable[[str, SubTask, str], Any],
        status_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        """Thực thi một task đơn lẻ có quản lý Semaphore, Timeout và cơ chế Retry tự động."""
        async with self.semaphore:
            task_statuses[task_id] = "RUNNING"
            logger.info("[Task %s] Running: %s", task_id, subtask_def.name)
            if status_callback:
                await status_callback({
                    "event": "task_start",
                    "data": {
                        "task_id": task_id,
                        "name": subtask_def.name
                    }
                })

            # 1. Thu thập kết quả từ các task dependency làm đầu vào
            dep_outputs_list = []
            for dep in subtask_def.dependencies:
                dep_output = task_outputs.get(dep, f"[Không có đầu ra từ {dep}]")
                dep_outputs_list.append(f"--- Kết quả từ {dep} ---\n{dep_output}")
            dependencies_outputs = "\n\n".join(dep_outputs_list) if dep_outputs_list else "Không có tác vụ phụ thuộc nào trước đó."

            # Thiết lập số lần retry dựa trên chiến lược
            max_retries = 0
            if self.strategy == ExecutionStrategy.QUALITY_FIRST:
                max_retries = 2
            elif self.strategy == ExecutionStrategy.BALANCED:
                max_retries = 1

            current_attempt = 0
            success = False
            last_error = ""
            recovery_prompt_instruction = ""

            while current_attempt <= max_retries and not success:
                if current_attempt > 0:
                    logger.warning("[Task %s] Retry %d/%d", task_id, current_attempt, max_retries)
                    if status_callback:
                        await status_callback({
                            "event": "task_retry",
                            "data": {
                                "task_id": task_id,
                                "attempt": current_attempt,
                                "max_retries": max_retries
                            }
                        })

                try:
                    # Chạy task thực tế qua callback có kèm timeout
                    async with asyncio.timeout(self.timeout_per_task):
                        # Nếu ở lượt retry và có hướng dẫn recovery từ LLM, ta có thể modify description của task
                        modified_subtask = subtask_def
                        if recovery_prompt_instruction:
                            modified_subtask = subtask_def.model_copy()
                            modified_subtask.description = f"{subtask_def.description}\n[Chỉ dẫn sửa lỗi từ lần chạy trước]: {recovery_prompt_instruction}"

                        raw_result = await execution_func(task_id, modified_subtask, dependencies_outputs)
                        task_outputs[task_id] = str(raw_result)
                        task_statuses[task_id] = "COMPLETED"
                        success = True
                        logger.info("[Task %s] Completed successfully", task_id)
                        if status_callback:
                            await status_callback({
                                "event": "task_complete",
                                "data": {
                                    "task_id": task_id,
                                    "output": str(raw_result)[:200] + "..." if len(str(raw_result)) > 200 else str(raw_result)
                                }
                            })
                except Exception as e:
                    last_error = str(e)
                    current_attempt += 1
                    logger.error("[Task %s] Error on attempt %d: %s", task_id, current_attempt, last_error)

                    if current_attempt <= max_retries:
                        # Gọi prompt sửa lỗi tự động để bổ sung chỉ dẫn cho lần retry kế tiếp
                        try:
                            recovery_prompt = get_prompt(
                                "ERROR_RECOVERY_PROMPT",
                                task_name=subtask_def.name,
                                task_description=subtask_def.description,
                                error_message=last_error,
                            )
                            recovery_resp = await self.llm.ainvoke(recovery_prompt)
                            recovery_prompt_instruction = recovery_resp.content if hasattr(recovery_resp, "content") else str(recovery_resp)
                        except Exception as inner_e:
                            logger.warning("Cannot create recovery prompt: %s", inner_e)
                            recovery_prompt_instruction = f"Hãy chú ý tránh lỗi: {last_error}"

            if not success:
                task_statuses[task_id] = "FAILED"
                task_errors[task_id] = last_error
                
                # Nếu không quan trọng và chiến lược cho phép bỏ qua, gán placeholder
                if not subtask_def.critical and self.strategy in [ExecutionStrategy.SPEED_FIRST, ExecutionStrategy.BALANCED]:
                    task_outputs[task_id] = f"[Tác vụ bị bỏ qua do lỗi thực thi]: {last_error}"
                    task_statuses[task_id] = "SKIPPED"
                    logger.warning("[Task %s] Skipped (non-critical failure)", task_id)
                    if status_callback:
                        await status_callback({
                            "event": "task_skipped",
                            "data": {
                                "task_id": task_id,
                                "error": last_error
                            }
                        })
                else:
                    task_outputs[task_id] = f"[Thất bại nghiêm trọng]: {last_error}"
                    logger.error("[Task %s] Critical failure!", task_id)
                    if status_callback:
                        await status_callback({
                            "event": "task_failed",
                            "data": {
                                "task_id": task_id,
                                "error": last_error
                            }
                        })

