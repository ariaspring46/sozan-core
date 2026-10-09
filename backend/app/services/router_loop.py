"""The decider loop of a seller turn, apart from the router core.

The decider chooses an action per round; the chat model sees that action's tool (or its toolset when
DECIDER_TOOL_GROUPS is on); a skill turns the first rounds into plan mode (suggest, then a revise with one goal);
read tools may continue the loop, a write ends it in a confirmation card. Everything here reads router state
through `rs` at call time, so tests that patch router_service still reach this code.
"""

from __future__ import annotations



class _Router:
    """router_service, looked up at call time: either module may be imported first (router_service imports this
    one at its end), and a test that patches router_service still reaches the code here."""

    def __getattr__(self, name: str):
        from app.services import router_service

        return getattr(router_service, name)


rs = _Router()

def _wants_apply(text: str) -> bool:
    return any(word in (text or "") for word in ("عوض", "اعمال", "انجام بده", "تغییر بده", "درست کن"))


_GROWTH_MARKS = (
    "فروشم",
    "فروش کم",
    "فروش کمه",
    "سود کم",
    "نرخ تبدیل",
    "تبدیل فروش",
    "رشد فروش",
    "قیف فروش",
    "حاشیه سود",
    "درآمد ماه",
)


def _wants_growth(text: str) -> bool:
    raw = text or ""
    from app.services.seller_tools import asks_sales

    if asks_sales(raw) and not any(word in raw for word in ("کمه", "کم شده", "چطور", "چیکار", "بیشتر")):
        return False  # «امروز چقدر فروختم» wants the number, not a growth plan
    if "قیمت" in raw and any(word in raw for word in ("عوض", "کن", "بکن", "بگذار", "بذار")) and "فروشم" not in raw and "نرخ تبدیل" not in raw:
        return False
    return any(mark in raw for mark in _GROWTH_MARKS)


def _growth_write_ok(name: str, goal: str) -> bool:
    """A growth experiment may open one existing tool only when that gap is already measured."""
    from app.services.skill_catalog import business_facts

    facts = business_facts()
    if name == "studio_chat" and "بدون عکس" in facts and any(word in goal for word in ("عکس", "تصویر")):
        return True
    if name == "set_voice_tone" and "لحن" in goal:
        return True
    return False


def _decider_state(spoken: str, media: dict | None, card_open: bool) -> dict:
    from app.services import decider_service
    from app.services.shop_service import current_shop

    shop = current_shop() or {}
    return decider_service.state_from(
        rs._messages(),
        shop=shop if isinstance(shop, dict) else {},
        card_open=card_open,
        last_post=rs._latest_post(spoken) is not None,
        media=media,
    )


async def _decider_result(spoken: str, media: dict | None, card_open: bool, decider) -> dict | None:
    from app.services import decider_service

    state = _decider_state(spoken, media, card_open)
    try:
        decision = await decider(state) if decider is not None else await decider_service.choose_with_retry(state)
    except Exception:
        return None
    if not isinstance(decision, dict):
        return None
    if decision.get("accepted"):
        plan = decider_service.plan_for(
            str(decision.get("action") or ""),
            spoken,
            frustrated=bool(decision.get("frustrated")),
            effort=str(decision.get("effort") or "normal"),
        )
    else:
        plan = decider_service.chips_for(list(decision.get("ranked") or []))
        plan["frustrated"] = bool(decision.get("frustrated"))
        plan["effort"] = str(decision.get("effort") or "quick")
    result = decider_service.as_result(plan, decision.get("observed") if isinstance(decision.get("observed"), dict) else {})
    rs._trace(
        path="decider",
        decider={
            "action": decision.get("action"),
            "probability": decision.get("probability"),
            "margin": decision.get("margin"),
            "accepted": decision.get("accepted"),
            "effort": decision.get("effort"),
            "refers_back": decision.get("refers_back"),
            "frustrated": decision.get("frustrated"),
            "media_kind": state.get("media_kind"),
        },
    )
    return result


def _subset_for(tool: str) -> list[dict]:
    """The decider's tool; with DECIDER_TOOL_GROUPS on, also the read tools of its groups (router_tools.toolset)."""
    if not tool or tool == "ask_user":
        return []
    from app.config import settings
    from app.services import router_tools

    wanted = set(router_tools.toolset(tool)) if getattr(settings, "decider_tool_groups", False) else {tool}
    return [item for item in rs.TOOLS if str((item.get("function") or {}).get("name") or "") in wanted]


def _overlay(base: dict, model_args: dict) -> dict:
    merged = dict(base)
    for key, value in model_args.items():
        if value in ("", None, [], {}):
            continue
        merged[key] = value
    return merged


def _goal_name() -> str:
    tid = rs._THREAD.get()
    return f"router-{tid}-goal.json" if tid else "router-goal.json"


def _load_goal() -> dict:
    row = rs.read_json(_goal_name(), {})
    return row if isinstance(row, dict) else {}


def _save_goal(goal: str, skill: str, suggestions: str, *, reached: bool) -> None:
    rs.write_json(
        _goal_name(),
        {"goal": goal, "skill": skill, "suggestions": suggestions[:800], "reached": reached},
    )


def _goal_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped.startswith("هدف"):
            parts = stripped.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return _short_goal(parts[1].strip())
    first = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return _short_goal(first[0]) if first else ""


def _short_goal(text: str) -> str:
    goal = text.strip()
    for sep in ("،", ".", "؛"):
        at = goal.find(sep)
        if at >= 25:
            goal = goal[:at]
            break
    return goal[:110]


async def _skill_plan(spoken: str, skill: str, mode: str, goal: str = "") -> str:
    from app.services import shop_service
    from app.services.turn_clock import expired, remaining

    if expired() or remaining() <= 0:
        return ""
    out = await shop_service.chat(spoken, skill=skill, mode=mode, goal=goal)
    picked = out.get("assistant") if isinstance(out.get("assistant"), dict) else rs._last_assistant(out)
    text = str(picked.get("text") or "").strip()
    return rs.re.sub(r"otp|api[_-]?key|jwt|bearer\s+\S+", "", text, flags=rs.re.I).strip()


def _add_tokens(total: dict, usage: object) -> None:
    if not isinstance(usage, dict):
        return
    total["promptTokens"] = int(total.get("promptTokens") or 0) + int(usage.get("promptTokens") or 0)
    total["completionTokens"] = int(total.get("completionTokens") or 0) + int(usage.get("completionTokens") or 0)


async def _steer_decider(spoken: str, media: dict | None, card_open: bool, decider, history: list, completer) -> dict | None:
    """Two rounds at most. The chat model sees only the decider's tool. None means the turn already answered."""
    from app.services import decider_service
    from app.services.turn_clock import expired, remaining

    state = _decider_state(spoken, media, card_open)
    if _wants_growth(spoken):
        from app.services.skill_catalog import remember_seller_metric

        remember_seller_metric(spoken)
    saved = _load_goal()
    if saved.get("goal") and not saved.get("reached") and not rs._wants_advice(spoken) and not _wants_growth(spoken):
        state["goal"] = str(saved.get("goal") or "")
        state["suggestions"] = str(saved.get("suggestions") or "done")
        state["planSkill"] = str(saved.get("skill") or "")
        state["phase"] = "act"
    messages = list(history)
    rounds: list[dict] = []
    spent = {"promptTokens": 0, "completionTokens": 0}
    carried: list[str] = []
    for round_index in range(5):
        if expired() or remaining() <= 0:
            rs._append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
            rs._emit("router-llm-fail", {"error": "budget"}, status="error")
            return None
        try:
            decision = await decider(state) if decider is not None else await decider_service.choose_with_retry(state)
        except Exception:
            decision = None
        if not isinstance(decision, dict):
            if state.get("lastTool"):
                rs._append("assistant", str((state.get("lastTool") or {}).get("text") or ""))
            rs._append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
            rs._emit("router-llm-fail", {"error": "decider"}, status="error")
            rs._trace(path="decider", loopEnough=True, tools=[], deciderRounds=rounds)
            return None
        loop_enough = bool(decision.get("loopEnough", True))
        if decision.get("accepted"):
            plan = decider_service.plan_for(
                str(decision.get("action") or ""),
                spoken,
                frustrated=bool(decision.get("frustrated")),
                effort=str(decision.get("effort") or "normal"),
            )
        else:
            plan = decider_service.chips_for(list(decision.get("ranked") or []))
            plan["frustrated"] = bool(decision.get("frustrated"))
            plan["effort"] = str(decision.get("effort") or "quick")
        skill = decider_service.chosen_skill(decision) if decision.get("accepted") else "none"
        if skill != "none" and isinstance(plan.get("arguments"), dict):
            plan["arguments"]["skill"] = skill
        subset = _subset_for(str(plan.get("tool") or ""))
        names = [str((item.get("function") or {}).get("name") or "") for item in subset]
        rounds.append({"action": decision.get("action"), "loopEnough": loop_enough, "tools": names})
        rs._trace(
            path="decider",
            loopEnough=loop_enough,
            tools=names,
            deciderRounds=rounds,
            decider={
                "action": decision.get("action"),
                "probability": decision.get("probability"),
                "margin": decision.get("margin"),
                "accepted": decision.get("accepted"),
                "effort": decision.get("effort"),
                "refers_back": decision.get("refers_back"),
                "frustrated": decision.get("frustrated"),
                "loopEnough": loop_enough,
                "skill": skill,
                "media_kind": state.get("media_kind"),
            },
            skill=skill,
            goal=state.get("goal") or "",
        )
        from app.services.skill_catalog import plans as skill_plans

        if skill_plans(skill):
            state["planSkill"] = skill
        if state.get("planSkill") and not state.get("suggestions"):
            text = await _skill_plan(spoken, str(state.get("planSkill") or ""), "suggest")
            if not text:
                rs._append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
                return None
            rs._append("assistant", "پیشنهادها:\n" + text)
            state["suggestions"] = text[:800]
            state["phase"] = "suggest"
            messages.append({"role": "assistant", "content": text[:800]})
            continue
        if state.get("planSkill") and not state.get("goal"):
            text = await _skill_plan(spoken, str(state.get("planSkill") or ""), "revise")
            if not text:
                rs._append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
                return None
            goal = _goal_line(text)
            rs._append("assistant", "پلن اصلاح:\n" + text)
            state["goal"] = goal
            state["phase"] = "revise"
            if str(state.get("planSkill") or "") == "ecommerce-growth-mba":
                from app.services.skill_catalog import append_business_plan

                append_business_plan(
                    diagnosis=str(state.get("suggestions") or ""),
                    revision=text,
                    goal=goal,
                )
            else:
                _save_goal(goal, str(state.get("planSkill") or ""), str(state.get("suggestions") or ""), reached=False)
            messages.append({"role": "assistant", "content": text[:800]})
            continue
        if state.get("goal") and bool(decision.get("goalReached", True)):
            if str(state.get("planSkill") or "") != "ecommerce-growth-mba":
                _save_goal(
                    str(state.get("goal") or ""),
                    str(state.get("planSkill") or skill),
                    str(state.get("suggestions") or ""),
                    reached=True,
                )
            rs._trace(goal=state.get("goal"), goalReached=True)
            return None
        observed = decision.get("observed") if isinstance(decision.get("observed"), dict) else {}
        if plan.get("direct") or not subset:
            result = decider_service.as_result(plan, observed)
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
            usage = dict(usage)
            _add_tokens(usage, spent)
            result["usage"] = usage
            return result
        try:
            try:
                model = await rs.asyncio.wait_for(completer(messages, subset), timeout=max(0.05, remaining()))
            except TimeoutError:
                if state.get("lastTool"):
                    rs._append("assistant", str((state.get("lastTool") or {}).get("text") or ""))
                rs._append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
                rs._emit("router-llm-fail", {"error": "budget"}, status="error")
                return None
            except Exception as first:
                if getattr(first, "budget_capped", False):
                    raise
                if expired() or remaining() < 1:
                    rs._append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
                    rs._emit("router-llm-fail", {"error": "budget"}, status="error")
                    return None
                await rs.asyncio.sleep(min(1.0, remaining()))
                model = await rs.asyncio.wait_for(completer(messages, subset), timeout=max(0.05, remaining()))
        except Exception as exc:
            if state.get("lastTool"):
                rs._append("assistant", str((state.get("lastTool") or {}).get("text") or ""))
            if getattr(exc, "budget_capped", False):
                rs._append("assistant", rs.BUDGET_CAPPED)
                rs._emit("router-budget-capped", {"reason": str(exc)[:40]}, status="error")
                return None
            rs._append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
            rs._emit("router-llm-fail", {"error": "unreachable"}, status="error")
            return None
        if not isinstance(model, dict):
            model = {}
        _add_tokens(spent, model.get("usage"))
        allowed = set(names)
        calls = [
            call
            for call in (model.get("tool_calls") or [])
            if isinstance(call, dict) and str(call.get("name") or "") in allowed
        ]
        plan_args = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
        if calls:
            raw_args = calls[0].get("arguments") if isinstance(calls[0].get("arguments"), dict) else {}
            name = str(calls[0].get("name") or plan.get("tool") or "")
        else:
            name = str(plan.get("tool") or "")
            raw_args = {}
        args = _overlay(plan_args, raw_args)
        if carried and name == "studio_chat":
            args["missingImages"] = carried
        if state.get("goal"):
            args["goal"] = state["goal"]
        result = {
            "text": str(model.get("text") or ""),
            "tool_calls": [{"name": name, "arguments": args}],
            "usage": dict(spent),
            "provider": str(model.get("provider") or ""),
            "model": str(model.get("model") or ""),
            "latencyMs": int(model.get("latencyMs") or 0),
            "frustrated": bool(plan.get("frustrated")),
            "direct": "",
            "finish_reason": str(model.get("finish_reason") or ""),
        }
        if name == "shop_chat" and state.get("goal") and not args.get("rebuild"):
            if state.get("phase") == "act" and rs._wants_advice(spoken) and not _wants_apply(spoken):
                _save_goal(
                    str(state.get("goal") or ""),
                    str(state.get("planSkill") or skill),
                    str(state.get("suggestions") or ""),
                    reached=True,
                )
                rs._trace(goal=state.get("goal"), goalReached=True)
                return None
            reply = await _skill_plan(spoken, skill or str(state.get("planSkill") or ""), "act", goal=str(state.get("goal") or ""))
            same = reply[:60] and reply[:60] == str(state.get("suggestions") or "")[:60]
            if same and rs._wants_advice(spoken):
                _save_goal(
                    str(state.get("goal") or ""),
                    str(state.get("planSkill") or skill),
                    str(state.get("suggestions") or ""),
                    reached=True,
                )
                rs._trace(goal=state.get("goal"), goalReached=True)
                return None
            if reply and not same:
                rs._append("assistant", reply)
                state["lastTool"] = {"name": name, "text": reply[:800]}
                state["phase"] = "act"
                messages.append({"role": "assistant", "content": reply[:800]})
            continue
        continues = (not loop_enough) and name in rs.READ_TOOLS and name != "ask_user" and round_index == 0
        if not continues:
            if _wants_growth(spoken) and name in rs.WRITE_TOOLS and not _growth_write_ok(name, str(state.get("goal") or "")):
                rs._append("assistant", "این پله سنجه ندارد. اول همان عدد را ثبت کن؛ صفحه را عوض نمی‌کنم.")
                return None
            return result
        try:
            reply, _extra = await rs._run_tool(
                name,
                args,
                source_text=spoken,
                media=media if isinstance(media, dict) else None,
            )
        except Exception as exc:
            await rs._say(spoken, rs._tool_error(name, exc), "tool_failed")
            return None
        if name == "status":
            carried = rs._missing_image_titles()
        state["lastTool"] = {"name": name, "text": str(reply or "")[:800]}
        messages.append({"role": "assistant", "content": str(reply or "")[:800]})
    if state.get("goal"):
        rs._append("assistant", f"هدف هنوز باز است: {state['goal']}")
    return None


def _shadow_after(out: dict, media: dict | None, *, decider) -> None:
    if decider is not None:
        return
    from app.services import decider_service
    from app.state_store import current_tenant

    if not decider_service.shadow_for(current_tenant()):
        return
    messages = out.get("messages") if isinstance(out, dict) else None
    if not isinstance(messages, list):
        return
    from app.services.shop_service import current_shop

    shop = current_shop() or {}
    pending = out.get("pendingConfirm") if isinstance(out, dict) else None
    state = decider_service.state_from(
        messages,
        shop=shop if isinstance(shop, dict) else {},
        card_open=bool(isinstance(pending, dict) and pending.get("id")),
        last_post=rs._latest_post() is not None,
        media=media,
    )
    decider_service.schedule_shadow(state)
