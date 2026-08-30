import sys
import asyncio
import json
from io import StringIO
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import logging

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def capture_display_results(result_data: dict) -> str:
    from rich.console import Console
    from cli import AligoCLI

    capture = StringIO()
    console = Console(file=capture, force_terminal=False, no_color=True)
    cli = AligoCLI()
    cli.console = console
    cli._display_results(result_data)
    return capture.getvalue().strip()



QUESTIONS = [
    "出差住宿标准是多少？",
    "如何报销差旅费用？需要哪些材料？",
    "我从3月11日从北京出发，在杭州出差一周，3月18日返回北京，帮我安排行程",
    "机票应该提前多久预订？有什么注意事项？",
    "我偏好住万豪酒店和希尔顿，喜欢坐国航和东航，座位要靠窗，家住北京朝阳区，请记住",
    "杭州下周的天气怎么样？",
    "从北京到深圳出差，住宿和交通标准分别是多少？",
    "查询我最近的差旅记录",
    "航班取消了怎么办？紧急情况联系谁？",
    "我要去上海出差5天，帮我规划详细行程",
]


async def main():
    print("="*70)
    print("CLI QA 测试 - 开始")
    print("="*70)


    print("\n[1/3] 初始化系统...")

    from config import LLM_CONFIG
    from config_agentscope import init_agentscope
    from agentscope.model import OpenAIChatModel
    from context.memory_manager import MemoryManager
    from agents.intention_agent import IntentionAgent
    from agents.orchestration_agent import OrchestrationAgent
    from agents.lazy_agent_registry import LazyAgentRegistry

    from agentscope.message import Msg


    init_agentscope()


    model = OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
        client_kwargs={"base_url": LLM_CONFIG["base_url"]},
        temperature=LLM_CONFIG.get("temperature", 0.7),
        max_tokens=LLM_CONFIG.get("max_tokens", 2000),
    )


    memory_manager = MemoryManager(
        user_id="test_user",
        session_id="test_session",
        llm_model=model
    )


    intention_agent = IntentionAgent(
        name="IntentionAgent",
        model=model
    )


    agent_cache = {}
    lazy_registry = LazyAgentRegistry(model, agent_cache, memory_manager)
    





    orchestrator = OrchestrationAgent(
        name="OrchestrationAgent",
        agent_registry=lazy_registry,
        memory_manager=memory_manager
    )

    print("✓ 系统初始化完成")


    print(f"\n[2/3] 运行 {len(QUESTIONS)} 个测试问题...")
    results = []

    for i, question in enumerate(QUESTIONS, 1):
        print(f"\n问题 {i}/{len(QUESTIONS)}: {question}")
        start = datetime.now()

        try:

            context_messages = [Msg(name="user", content=question, role="user")]
            intention_result = await intention_agent.reply(context_messages)


            orchestration_result = await orchestrator.reply(intention_result)


            result_data = json.loads(orchestration_result.content)
            duration = (datetime.now() - start).total_seconds()
            answer = capture_display_results(result_data)

            results.append({
                "num": i,
                "question": question,
                "answer": answer,
                "status": "success",
                "duration": round(duration, 2)
            })
            print(f"✓ 完成 ({duration:.1f}s)")

        except Exception as e:
            duration = (datetime.now() - start).total_seconds()
            results.append({
                "num": i,
                "question": question,
                "answer": f"错误: {str(e)}",
                "status": "error",
                "duration": round(duration, 2)
            })
            print(f"✗ 失败: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(0.5)


    print("\n[3/3] 保存结果...")
    save_results(results)
    print("✓ 完成")


    success = sum(1 for r in results if r["status"] == "success")
    total_time = sum(r["duration"] for r in results)
    print(f"\n{'='*70}")
    print(f"统计: {success}/{len(results)} 成功, 总耗时 {total_time:.1f}s")
    print(f"{'='*70}\n")


def save_results(results: List[Dict]):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = project_root / "tests" / "results" / f"qa_test_{timestamp}.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, 'w', encoding='utf-8') as f:

        f.write(f"# CLI QA 测试报告\n\n")
        f.write(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")


        success = sum(1 for r in results if r["status"] == "success")
        total_time = sum(r["duration"] for r in results)
        f.write(f"## 统计\n\n")
        f.write(f"- 总问题: {len(results)}\n")
        f.write(f"- 成功: {success} ({success/len(results)*100:.1f}%)\n")
        f.write(f"- 失败: {len(results)-success}\n")
        f.write(f"- 总耗时: {total_time:.1f}秒\n")
        f.write(f"- 平均: {total_time/len(results):.1f}秒/问题\n\n")


        f.write(f"## QA 对\n\n")
        for r in results:
            icon = "✅" if r["status"] == "success" else "❌"
            f.write(f"### {icon} Q{r['num']}: {r['question']}\n\n")
            f.write(f"**耗时**: {r['duration']}秒\n\n")
            f.write(f"**回答**:\n\n```\n{r['answer']}\n```\n\n")
            f.write(f"---\n\n")

    print(f"结果已保存: {output}")


if __name__ == "__main__":
    asyncio.run(main())
