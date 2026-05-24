import json
import asyncio
from pathlib import Path

from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from datasets import Dataset

from src.agent.assistant import invoke_agent
from src.rag.ingest import ingest_repository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_questions(path: Path) -> list[dict]:
    questions = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                questions.append(json.loads(line))
    return questions


def _build_prompt(question: str, contexts: list[str]) -> str:
    context_block = "\n\n".join(
        f"[Context {index + 1}]\n{context}" for index, context in enumerate(contexts)
    )
    return (
        "Answer the question using only the repository context below. "
        "If the context is insufficient, say so clearly.\n\n"
        f"{context_block}\n\nQuestion: {question}"
    )

async def run_eval():
    questions_path = PROJECT_ROOT / "eval" / "questions.jsonl"
    questions = _load_questions(questions_path)

    retriever, _ = ingest_repository(PROJECT_ROOT, collection_name="repo_docs_eval")

    data = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": [],
        "ground_truths": [],
    }

    for question_row in questions:
        question = question_row["question"]
        retrieved_docs = retriever.search(question, k=5)
        contexts = [doc.page_content for doc in retrieved_docs]
        answer = await invoke_agent(_build_prompt(question, contexts))
        ground_truth = question_row.get("expected_behavior") or question_row.get("expected_file") or ""

        data["question"].append(question)
        data["answer"].append(answer)
        data["contexts"].append(contexts)
        data["ground_truth"].append(ground_truth)
        data["ground_truths"].append([ground_truth] if ground_truth else [])

    dataset = Dataset.from_dict(data)
    
    # Run evaluation
    result = evaluate(
        dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        ],
    )
    
    print("Evaluation Results:")
    print(result)
    
    # Save results
    result.to_pandas().to_csv(PROJECT_ROOT / "eval" / "results.csv", index=False)

if __name__ == "__main__":
    asyncio.run(run_eval())
