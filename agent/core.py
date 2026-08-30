

import json
import os
import sys
import uuid
from typing import Any, Dict, Optional

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agentscope.model import OpenAIChatModel
from agentscope.message import Msg

from config_agentscope import init_agentscope
from config import LLM_CONFIG, SYSTEM_CONFIG, RESILIENCE_CONFIG
from context.memory_manager import MemoryManager
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from utils.llm_resilience import retry_with_backoff
from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent

_AGENTSCOPE_INITED = False

AGENT_DISPLAY_NAMES = {
    "event_collection": "事项收集",
    "preference": "偏好管理",
    "itinerary_planning": "行程规划",
    "information_query": "信息查询",
    "rag_knowledge": "知识库查询",
    "memory_query": "记忆查询",
}


class AligoCore:

    def __init__(self, user_id: str = "default_user", session_id: Optional[str] = None):
        self.user_id = user_id
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.memory_manager = None
        self.orchestrator = None
        self.intention_agent = None
        self.model = None
        self._agent_cache = {}
        self.circuit_breaker = None

    async def initialize(self):
        global _AGENTSCOPE_INITED
        if not _AGENTSCOPE_INITED:
            init_agentscope()
            _AGENTSCOPE_INITED = True

        timeout_sec = SYSTEM_CONFIG.get("timeout", 60)
        self.model = OpenAIChatModel(
            model_name=LLM_CONFIG["model_name"],
            api_key=LLM_CONFIG["api_key"],
            client_kwargs={
                "base_url": LLM_CONFIG["base_url"],
                "timeout": float(timeout_sec),
            },
            temperature=LLM_CONFIG.get("temperature", 0.7),
            max_tokens=LLM_CONFIG.get("max_tokens", 2000),
        )

        self.memory_manager = MemoryManager(
            user_id=self.user_id,
            session_id=self.session_id,
            llm_model=self.model,
        )

        self.intention_agent = IntentionAgent(
            name="IntentionAgent",
            model=self.model,
        )

        from agents.lazy_agent_registry import LazyAgentRegistry
        self._agent_cache = {}
        lazy_registry = LazyAgentRegistry(
            model=self.model,
            cache=self._agent_cache,
            memory_manager=self.memory_manager,
        )

        self.orchestrator = OrchestrationAgent(
            name="OrchestrationAgent",
            agent_registry=lazy_registry,
            memory_manager=self.memory_manager,
        )

        rc = RESILIENCE_CONFIG
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=rc.get("circuit_failure_threshold", 5),
            recovery_timeout_sec=rc.get("circuit_recovery_timeout_sec", 60.0),
            half_open_successes=rc.get("circuit_half_open_successes", 2),
        )

    async def process_query(self, user_input: str, web_context: str = "") -> Dict[str, Any]:
        if self.circuit_breaker:
            try:
                self.circuit_breaker.raise_if_open()
            except CircuitOpenError:
                return {"ok": False, "data": {}, "message": "⚠ 服务暂时不可用，请稍后再试。"}

        rc = RESILIENCE_CONFIG
        max_retries = rc.get("max_retries", 3)

        long_term_summary = await self._get_long_term_summary(user_input)
        recent_context = self.memory_manager.short_term.get_recent_context(n_turns=5)
        context_messages = []
        if long_term_summary:
            context_messages.append(Msg(name="system", content=long_term_summary, role="system"))
        if web_context:
            context_messages.append(Msg(name="system", content=web_context, role="system"))
        for msg in recent_context:
            context_messages.append(Msg(name=msg["role"], content=msg["content"], role=msg["role"]))
        context_messages.append(Msg(name="user", content=user_input, role="user"))

        try:
            intention_result = await retry_with_backoff(
                lambda: self.intention_agent.reply(context_messages),
                max_retries=max_retries,
                base_delay_sec=rc.get("retry_base_delay_sec", 1.0),
                max_delay_sec=rc.get("retry_max_delay_sec", 30.0),
            )
            if self.circuit_breaker:
                self.circuit_breaker.record_success()
        except CircuitOpenError:
            return {"ok": False, "data": {}, "message": "⚠ 服务暂时不可用，请稍后再试。"}
        except Exception as e:
            if self.circuit_breaker:
                self.circuit_breaker.record_failure()
            return {"ok": False, "data": {}, "message": f"意图识别失败：{e}"}

        try:
            intention_data = json.loads(intention_result.content)
        except json.JSONDecodeError:
            return {"ok": False, "data": {}, "message": "❌ 无法理解您的需求，请重新描述"}

        self.memory_manager.add_message("user", user_input)

        try:
            orchestration_result = await retry_with_backoff(
                lambda: self.orchestrator.reply(intention_result),
                max_retries=max_retries,
                base_delay_sec=rc.get("retry_base_delay_sec", 1.0),
                max_delay_sec=rc.get("retry_max_delay_sec", 30.0),
            )
            if self.circuit_breaker:
                self.circuit_breaker.record_success()
        except CircuitOpenError:
            return {"ok": False, "data": {}, "message": "⚠ 服务暂时不可用，请稍后再试。"}
        except Exception as e:
            if self.circuit_breaker:
                self.circuit_breaker.record_failure()
            return {"ok": False, "data": {}, "message": f"执行失败：{e}"}

        try:
            result_data = json.loads(orchestration_result.content)
        except json.JSONDecodeError:
            result_data = {"error": "解析结果失败"}

        self.memory_manager.add_message("assistant", json.dumps(result_data, ensure_ascii=False))
        return {"ok": True, "data": result_data, "message": ""}

    async def _get_long_term_summary(self, user_input: str = "") -> str:
        summary_parts = []

        prefs = self.memory_manager.long_term.get_preference()
        if prefs:
            pref_lines = ["【用户背景信息】（来自长期记忆，可用于推断缺失信息）"]
            for pref_key, pref_value in prefs.items():
                if pref_value:
                    if isinstance(pref_value, list):
                        pref_lines.append(f"• {pref_key}: {', '.join(pref_value)}")
                    else:
                        pref_lines.append(f"• {pref_key}: {pref_value}")
            if len(pref_lines) > 1:
                summary_parts.extend(pref_lines)

        chat_summary = await self.memory_manager.get_long_term_summary_async(max_messages=50)
        if chat_summary:
            summary_parts.append("\n【历史会话总结】")
            summary_parts.append(chat_summary)

        all_trips = self.memory_manager.long_term.get_trip_history(limit=None)
        if all_trips:
            relevant_trips = []
            other_trips = []
            for trip in all_trips:
                origin = trip.get("origin", "") or ""
                destination = trip.get("destination", "") or ""
                if (origin and origin in user_input) or (destination and destination in user_input):
                    relevant_trips.append(trip)
                else:
                    other_trips.append(trip)

            trips_to_show = relevant_trips[:2] + other_trips[:1]
            if trips_to_show:
                summary_parts.append("\n【历史行程】")
                for i, trip in enumerate(trips_to_show[:3], 1):
                    origin = trip.get("origin", "未知")
                    destination = trip.get("destination", "未知")
                    start_date = trip.get("start_date", "")
                    purpose = trip.get("purpose", "")
                    relevance_mark = "✦ " if trip in relevant_trips else ""
                    summary_parts.append(
                        f"{i}. {relevance_mark}{origin} → {destination} ({start_date}) - {purpose}"
                    )

        return "\n".join(summary_parts) if summary_parts else ""


def render_result_plain(result_data: Dict[str, Any]) -> str:
    lines = []
    results = result_data.get("results", [])

    if not results:
        status = result_data.get("status", "unknown")
        if status == "no_agents":
            lines.append("✓ 好的，我已记录下来。")
            lines.append("")
            lines.append("💡 您可以继续补充信息，或者尝试：")
            lines.append("  • 规划行程：「帮我规划去北京的行程」")
            lines.append("  • 查询信息：「北京的天气怎么样」")
            lines.append("  • 问问题：「差旅标准是多少」")
        else:
            lines.append("未能获取有效结果，请重新描述您的需求。")
        return "\n".join(lines)

    agents_called = []
    for r in results:
        agent_name = r.get("agent_name", "")
        status = r.get("status", "")
        disp = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
        if status == "success":
            agents_called.append(f"{disp} ✓")
        elif status == "error":
            agents_called.append(f"{disp} ✗")
        else:
            agents_called.append(f"{disp} ?")
    if agents_called:
        lines.append("🤖 调用智能体: " + ", ".join(agents_called))
        lines.append("")

    body = _render_results_body(results)
    if body:
        lines.append(body)
    else:
        lines.append("✓ 已处理您的请求。")

    return "\n".join(lines).strip()


def _render_results_body(results) -> str:
    lines = []
    has_output = False

    for result in results:
        agent_name = result.get("agent_name", "")
        status = result.get("status", "")
        data = result.get("data", {}) or {}
        shown = False

        if status == "error":
            err = data.get("error", "未知错误")
            disp = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
            lines.append(f"❌ {disp}执行失败: {err}")
            has_output = True
            continue

        if status != "success" and not (agent_name == "rag_knowledge" and status == "no_knowledge"):
            continue

        if agent_name == "itinerary_planning":
            itinerary = data.get("itinerary")
            if not itinerary and "data" in data and isinstance(data["data"], dict):
                itinerary = data["data"].get("itinerary")
            if itinerary:
                title = itinerary.get("title", "行程规划")
                lines.append(f"✈️ {title}")
                lines.append(f"时长: {itinerary.get('duration', '未知')}")
                lines.append("")
                for day_plan in itinerary.get("daily_plans", []):
                    day_num = day_plan.get("day", 1)
                    lines.append(f"第 {day_num} 天")
                    activities = day_plan.get("activities") or day_plan.get("time_slots") or []
                    for slot in activities:
                        t = slot.get("time", "")
                        act = slot.get("activity") or slot.get("location") or ""
                        desc = slot.get("description", "")
                        transport = slot.get("transport", "")
                        lines.append(f"  {t} - {act}")
                        if desc:
                            lines.append(f"    {desc}")
                        if transport:
                            lines.append(f"    🚇 {transport}")
                    meals = day_plan.get("meals", {})
                    if meals:
                        lines.append("")
                        if meals.get("lunch"):
                            lines.append(f"  🍜 {meals['lunch']}")
                        if meals.get("dinner"):
                            lines.append(f"  🍽️ {meals['dinner']}")
                    lines.append("")
                notes = itinerary.get("notes", [])
                if notes:
                    lines.append("📌 注意事项")
                    for note in notes:
                        lines.append(f"  • {note}")
                shown = True

        elif agent_name == "preference":
            raw_prefs = data.get("preferences")
            if not raw_prefs and "data" in data and isinstance(data["data"], dict):
                raw_prefs = data["data"].get("preferences")
            if isinstance(raw_prefs, dict):
                prefs_list = raw_prefs.get("preferences", [])
            else:
                prefs_list = raw_prefs if isinstance(raw_prefs, list) else []
            if prefs_list:
                lines.append("✓ 已更新您的偏好设置")
                type_names = {
                    "home_location": "常驻地",
                    "transportation_preference": "交通偏好",
                    "hotel_brands": "酒店偏好",
                    "airlines": "航空公司偏好",
                    "seat_preference": "座位偏好",
                    "meal_preference": "餐食偏好",
                    "budget_level": "预算等级",
                }
                for pref in prefs_list:
                    pref_type = pref.get("type", "")
                    pref_value = pref.get("value", "")
                    action = pref.get("action", "replace")
                    display_type = type_names.get(pref_type, pref_type)
                    action_text = "追加" if action == "append" else "设置为"
                    lines.append(f"  • {display_type} {action_text} {pref_value}")
                shown = True
                has_itinerary = any(r.get("agent_name") == "itinerary_planning" for r in results)
                if not has_itinerary:
                    lines.append("")
                    lines.append("💡 下次规划行程时会参考这些偏好。")
            else:
                err = data.get("error", "")
                if err:
                    lines.append(f"偏好未保存: {err}")
                    shown = True

        elif agent_name == "event_collection":
            origin = data.get("origin") or (data.get("data", {}) or {}).get("origin")
            destination = data.get("destination") or (data.get("data", {}) or {}).get("destination")
            start_date = data.get("start_date") or (data.get("data", {}) or {}).get("start_date")
            end_date = data.get("end_date") or (data.get("data", {}) or {}).get("end_date")
            missing_info = data.get("missing_info") or (data.get("data", {}) or {}).get("missing_info") or []

            has_itinerary = any(r.get("agent_name") == "itinerary_planning" for r in results)
            info_shown = False
            if not has_itinerary:
                if destination or origin:
                    lines.append("✓ 已收集行程信息")
                    if origin:
                        lines.append(f"  • 出发地: {origin}")
                    if destination:
                        lines.append(f"  • 目的地: {destination}")
                    if start_date:
                        lines.append(f"  • 出发日期: {start_date}")
                    if end_date:
                        lines.append(f"  • 返程日期: {end_date}")
                    info_shown = True
            if missing_info:
                lines.append(f"💡 还需要补充: {', '.join(missing_info)}")
                info_shown = True
            if info_shown:
                shown = True

        elif agent_name == "information_query":
            query_results = data.get("results")
            if not query_results and "data" in data and isinstance(data["data"], dict):
                query_results = data["data"].get("results")
            if not query_results:
                query_results = data
            if not isinstance(query_results, dict):
                query_results = {}

            summary = query_results.get("summary", "")
            sources = query_results.get("sources", []) or []
            message = query_results.get("message", "")
            error = query_results.get("error", "")

            if summary:
                lines.append(summary)
                shown = True
            elif message:
                lines.append(message)
                shown = True
            elif error:
                lines.append(error)
                shown = True
            if sources:
                lines.append("")
                lines.append("参考来源")
                for i, source in enumerate(sources[:3], 1):
                    url = source.get("url", "") if isinstance(source, dict) else str(source)
                    lines.append(f"  {i}. {url}")
                shown = True

        elif agent_name == "rag_knowledge":
            answer = data.get("answer")
            if not answer and "data" in data and isinstance(data["data"], dict):
                answer = data["data"].get("answer")
            if not answer:
                answer = data.get("content") or (data.get("data", {}) or {}).get("content")
            if isinstance(answer, dict):
                answer = answer.get("answer", str(answer))
            if isinstance(answer, str) and answer.strip().startswith("{") and answer.strip().endswith("}"):
                try:
                    obj = json.loads(answer)
                    if isinstance(obj, dict) and "answer" in obj:
                        answer = obj["answer"]
                except Exception:
                    pass
            if answer:
                lines.append(answer)
                shown = True

        elif agent_name == "memory_query":
            query_result = data.get("answer") or data.get("result") or data.get("content")
            if not query_result and "data" in data and isinstance(data["data"], dict):
                inner = data["data"]
                query_result = inner.get("answer") or inner.get("result") or inner.get("content")
            if query_result:
                lines.append(query_result)
                shown = True

        if not shown:
            common_keys = ["answer", "content", "result", "message", "summary", "text", "description"]
            fallback_content = ""
            for k in common_keys:
                if k in data and isinstance(data[k], str) and data[k].strip():
                    fallback_content = data[k]
                    break
            if not fallback_content and "data" in data and isinstance(data["data"], dict):
                for k in common_keys:
                    if k in data["data"] and isinstance(data["data"][k], str) and data["data"][k].strip():
                        fallback_content = data["data"][k]
                        break
            if fallback_content:
                lines.append(fallback_content)
                shown = True
            else:
                disp = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
                lines.append(f"✓ {disp}已完成")
                shown = True

        if shown:
            has_output = True

    return "\n".join(lines).strip() if has_output else ""
