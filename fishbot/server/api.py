import json

from bot import fishbot
from settings import load_settings, save_settings, update_settings
from budget import calculate_work_income, format_money, shorten_money
from picker import pick_point, pick_region


def _ok(result):
    return json.dumps({"status": "ok", "result": result})


def _err(reason):
    return json.dumps({"status": "error", "reason": str(reason)})


def handle_message(message_str):
    try:
        req = json.loads(message_str or "{}")
        action = req.get("action")

        if action == "status":
            return _ok({"settings": load_settings(), "bot": fishbot.status()})
        if action == "save_settings":
            settings = update_settings(req.get("settings", {}))
            fishbot.update_settings(settings)
            return _ok(settings)
        if action == "live_settings":
            settings = update_settings(req.get("settings", {}))
            return _ok({"settings": settings, "bot": fishbot.update_settings(settings)})
        if action == "set_region":
            s = load_settings()
            s["bbox"] = _norm_rect(req)
            return _ok(save_settings(s))
        if action == "pick_region":
            s = load_settings()
            s["bbox"] = pick_region()
            return _ok(save_settings(s))
        if action == "set_click_location":
            s = load_settings()
            s["clickLocation"] = _norm_point(req)
            return _ok(save_settings(s))
        if action == "pick_click_location":
            s = load_settings()
            s["clickLocation"] = pick_point()
            return _ok(save_settings(s))
        if action == "start":
            settings = update_settings(req.get("settings", {}))
            return _ok(fishbot.start(settings))
        if action == "stop":
            return _ok(fishbot.stop())
        if action == "budget":
            settings = update_settings(req.get("settings", {}))
            data = calculate_work_income(
                int(req.get("overallLevel", 1) or 1),
                int(req.get("fishermanLevel", 1) or 1),
                bool(req.get("excellentEmployee", False)),
                float(req.get("moodPercent", 0.7) or 0.7),
                settings,
            )
            return _ok({
                "estimatedIncome": data[0],
                "excellentEmployeeBonus": data[1],
                "humanizationExpense": data[2],
                "formatted": {
                    "income": shorten_money(data[0]),
                    "bonus": format_money(data[1]),
                    "expense": format_money(data[2]),
                },
            })

        return _err("Unknown Fishbot action: " + str(action))
    except Exception as exc:
        return _err(exc)


def _screen_size():
    return fishbot.screen_size()


def _norm_point(req):
    w, h = _screen_size()
    return [
        int(max(0, min(1, float(req.get("x", 0)))) * w),
        int(max(0, min(1, float(req.get("y", 0)))) * h),
    ]


def _norm_rect(req):
    w, h = _screen_size()
    x1 = int(max(0, min(1, float(req.get("fromX", 0)))) * w)
    y1 = int(max(0, min(1, float(req.get("fromY", 0)))) * h)
    x2 = int(max(0, min(1, float(req.get("toX", 1)))) * w)
    y2 = int(max(0, min(1, float(req.get("toY", 1)))) * h)
    return [min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)]
