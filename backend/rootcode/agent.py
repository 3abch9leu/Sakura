"""
ROOTAgent - LLM with tool calling. The LLM never computes numbers: it calls the engines.

Works with any OpenAI-compatible endpoint:
  * Groq (free tier, fast):   set GROQ_API_KEY            (model: GROQ_MODEL, default qwen/qwen3.8-27b)
  * Ollama on your own GPU:   set LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=qwen2.5:7b
Backends are tried in order (LLM_BASE_URL, Groq, local Ollama), so the demo survives losing Wi-Fi.
Model names change often: check the provider's model list and set the env var.
"""
import json
import os
from openai import OpenAI

from . import config as C
from .evaluate import Context
from .optimizer import run
from .solar import facade_sun, peak_hour

SYSTEM = """You are ROOTAgent, the design assistant of ROOTCODE: passive building tiles that shade an
apartment window, feed edible plants by gravity and can optionally cool by evaporation, with no
electricity needed once installed.
Rules:
- Every number you give must come from a tool result. Never invent measurements, litres or kWh.
- Ask for missing essentials (facade orientation, plants, water the household can spare) before designing.
- Explain the three Pareto designs (Water Saver, Shade Maximizer, Balanced) and the trade-off between them,
  and compare with the conventional tile.
- If evaporative cooling is OFF in a design, explain that the optimizer judged the water better spent on plants
  in that climate.
- Say clearly that results are model estimates to be confirmed by measurement.
- Reply in the user's language (Tunisian Darija, French, Arabic, English or Japanese)."""

TOOLS = [
    {"type": "function", "function": {
        "name": "design_tiles",
        "description": "Run the ROOTCODE optimizer (hydraulics + solar + NSGA-II) and return 3 Pareto designs plus a conventional baseline.",
        "parameters": {"type": "object", "properties": {
            "plants": {"type": "array", "items": {"type": "string", "enum": list(C.PLANT_DEMAND_L_DAY)},
                       "description": "1 to 6 plants for one root tile"},
            "facade": {"type": "string", "enum": list(C.FACADE_AZIMUTHS)},
            "rh": {"type": "number", "description": "daytime relative humidity 0-1 (coastal Tunis ~0.55, inland ~0.3)"},
            "window_w": {"type": "number", "description": "window width in metres"},
            "window_h": {"type": "number", "description": "window height in metres"},
            "water_available_l_day": {"type": "number"},
            "root_tiles": {"type": "integer"},
            "lat": {"type": "number"}, "lon": {"type": "number"},
        }, "required": ["plants", "facade"]}}},
    {"type": "function", "function": {
        "name": "sun_on_facade",
        "description": "Clear-sky solar energy reaching a facade on a hot summer day, and the peak hour.",
        "parameters": {"type": "object", "properties": {
            "facade": {"type": "string", "enum": list(C.FACADE_AZIMUTHS)},
            "lat": {"type": "number"}, "lon": {"type": "number"},
        }, "required": ["facade"]}}},
]


def _round(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def tool_design_tiles(**kw):
    ctx = Context(**{k: v for k, v in kw.items() if v is not None})
    out = run(ctx, n_gen=100)
    res = {}
    for name, v in out["designs"].items():
        r = v["result"]
        res[name] = {"design": v["design"].to_dict(), "objectives": r["objectives"],
                     "heat_reduction_pct": r["panel"]["heat_reduction_pct"],
                     "pockets": r["pockets"], "distribution_cv": r["distribution_cv"],
                     "drip_minutes": r["hydraulics"]["drain_time_min"]}
    res["panel"] = {"n_tiles": ctx.n_tiles, "root_tiles": min(ctx.root_tiles, ctx.n_tiles)}
    res["units"] = UNITS
    return _round(res)


# Explicit units so the LLM does not mislabel numbers (e.g. a deficit fraction read as litres).
UNITS = {
    "objectives.water_l_day": "litres per day for the WHOLE window (all root tiles together)",
    "objectives.heat_kwh_day": "kWh per day of solar heat reaching the room through the whole window",
    "objectives.plant_deficit": "FRACTION 0-1 of total plant water need not met (0.05 means 5 %), not litres",
    "design.water_l_day": "litres per day poured into ONE root tile",
    "heat_reduction_pct": "percent of heat blocked compared with the bare window",
    "pockets[].received_l / need_l": "litres per day per plant pocket; ratio = received/need",
    "drip_minutes": "minutes for the daily water to drain into the pockets",
}


def tool_sun_on_facade(facade, lat=C.DEFAULT_LAT, lon=C.DEFAULT_LON):
    s = facade_sun(lat, lon, float(C.FACADE_AZIMUTHS[facade]))
    return {"facade": facade, "kwh_per_m2_day": round(s["daily_kwh_m2"], 2), "peak_hour": peak_hour(s),
            "note": "clear-sky July estimate"}


DISPATCH = {"design_tiles": tool_design_tiles, "sun_on_facade": tool_sun_on_facade}


OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434/v1"
LAST_BACKEND = {}   # which backend answered the last /chat (shown by /health)


def backends():
    """Candidate (name, base_url, api_key, model) in priority order."""
    out = []
    if os.getenv("LLM_BASE_URL"):
        out.append(("custom", os.environ["LLM_BASE_URL"], os.getenv("LLM_API_KEY", "ollama"),
                    os.getenv("LLM_MODEL", "qwen2.5:7b")))
    if os.getenv("GROQ_API_KEY"):
        out.append(("groq", "https://api.groq.com/openai/v1", os.environ["GROQ_API_KEY"],
                    os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")))
    if not any(b[1].rstrip("/").replace("localhost", "127.0.0.1") == OLLAMA_DEFAULT_URL for b in out):
        out.append(("ollama", OLLAMA_DEFAULT_URL, "ollama", os.getenv("LLM_MODEL", "qwen2.5:7b")))
    return out


def make_client():
    """First configured backend (kept for compatibility)."""
    _, url, key, model = backends()[0]
    return OpenAI(base_url=url, api_key=key), model


def _complete(client, model, msgs, tools=None):
    return client.chat.completions.create(model=model, messages=msgs, tools=tools or TOOLS,
                                          tool_choice="auto", temperature=0.2)


def _completion(msgs, start=0, tools=None, timeout=180):
    """Try backends from index `start` until one answers (Groq rate-limited / offline -> Ollama).
    A short rate-limit wait (<= 10 s) is retried once on the same backend first.
    Returns (backend_index, response)."""
    import re
    import time
    from openai import RateLimitError
    errors = []
    cands = backends()
    for i in range(start, len(cands)):
        name, url, key, model = cands[i]
        client = OpenAI(base_url=url, api_key=key, timeout=timeout, max_retries=0)
        for attempt in range(2):
            try:
                resp = _complete(client, model, msgs, tools)
                LAST_BACKEND.update(name=name, model=model)
                return i, resp
            except RateLimitError as e:
                wait = re.search(r"try again in ([\d.]+)s", str(e))
                if attempt == 0 and wait and float(wait.group(1)) <= 10:
                    time.sleep(float(wait.group(1)) + 0.5)
                    continue
                errors.append(f"{name}/{model}: rate limited")
                break
            except Exception as e:
                errors.append(f"{name}/{model}: {type(e).__name__}: {str(e)[:150]}")
                break
    raise RuntimeError("No LLM backend answered. " + " | ".join(errors))


def chat(messages, max_steps=4):
    """messages: list of {'role','content'}. Returns (reply_text, updated_messages, last_design)."""
    msgs = [{"role": "system", "content": SYSTEM}] + messages
    last_design = None
    backend_idx = 0
    for _ in range(max_steps):
        backend_idx, resp = _completion(msgs, backend_idx)   # sticks to the backend that last worked
        m = resp.choices[0].message
        if not m.tool_calls:
            msgs.append({"role": "assistant", "content": m.content})
            return m.content, msgs[1:], last_design
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [tc.model_dump() for tc in m.tool_calls]})
        for tc in m.tool_calls:
            try:
                result = DISPATCH[tc.function.name](**json.loads(tc.function.arguments or "{}"))
                if tc.function.name == "design_tiles":
                    last_design = result
            except Exception as e:  # report tool errors to the model instead of crashing the demo
                result = {"error": str(e)}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    return "Sorry, I could not finish the design. Please try again.", msgs[1:], last_design


if __name__ == "__main__":
    history = []
    print("ROOTAgent (Ctrl+C to quit)")
    while True:
        history.append({"role": "user", "content": input("> ")})
        reply, history, _ = chat(history)
        print(reply)


# ================================================================ Energy & Comfort Companion (bill mode)
BILL_SYSTEM = """You are the INBETWEEN Energy & Comfort Companion. You help Tunisian households understand their
STEG electricity bill and stay comfortable with less energy. Philosophy: "Making Room for Life".
Rules:
- Reply in the user's language: Tunisian Darija (in the same script the user writes: Arabic letters or Latin
  "3arbizi"), Modern Standard Arabic, French or English. Keep it short, warm and practical.
- Every number must come from the BILL CONTEXT below or a tool result. Never do money arithmetic yourself:
  call compute_bill or appliance_energy. Never invent tariffs, savings or percentages.
- For facts about STEG billing or ANME advice, call search_official_docs and cite the source URL.
- If the verification status is "unavailable" or a value is missing, say so and ask the user for it.
- Never claim INBETWEEN saves a given amount of electricity or money: its shading reduces solar heat at the
  window, but electricity savings have not yet been measured or validated.
- Do not ask for or repeat personal data (name, address, customer number)."""

BILL_TOOLS = [
    {"type": "function", "function": {
        "name": "compute_bill",
        "description": "Official STEG residential tariff calculation (electricity part) for a consumption and period.",
        "parameters": {"type": "object", "properties": {
            "consumption_kwh": {"type": "number"}, "months": {"type": "number"},
            "power_kva": {"type": "number", "description": "subscribed power in kVA"}},
            "required": ["consumption_kwh"]}}},
    {"type": "function", "function": {
        "name": "appliance_energy",
        "description": "kWh used by appliances (power x hours x days) and, if a bill is known, the priced bill impact.",
        "parameters": {"type": "object", "properties": {
            "appliances": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "power_w": {"type": "number"}, "hours_per_day": {"type": "number"},
                "days": {"type": "number"}, "quantity": {"type": "number"},
                "reduce_hours_per_day": {"type": "number"}}, "required": ["power_w", "hours_per_day", "days"]}},
            "setpoint_current_c": {"type": "number"}, "setpoint_target_c": {"type": "number"}},
            "required": ["appliances"]}}},
    {"type": "function", "function": {
        "name": "search_official_docs",
        "description": "Search official STEG billing/tariff pages and ANME energy advice. Returns snippets with URLs.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "sun_on_facade",
        "description": "Clear-sky solar energy reaching a facade on a hot summer day, and the peak hour.",
        "parameters": {"type": "object", "properties": {
            "facade": {"type": "string", "enum": list(C.FACADE_AZIMUTHS)},
            "lat": {"type": "number"}, "lon": {"type": "number"}}, "required": ["facade"]}}},
]


def bill_chat(messages, bill=None, verification=None, max_steps=4, timeout=180):
    """
    messages: [{'role','content'}] user/assistant turns. bill: verified fields WITHOUT personal data.
    Returns (reply, updated_messages, sources). Raises RuntimeError if no LLM backend answers.
    """
    from . import energy_advisor as EA
    from .tariff import compute
    sources = []

    def t_compute(consumption_kwh, months=None, power_kva=None):
        return compute(consumption_kwh, months, power_kva)

    def t_appliance(appliances, setpoint_current_c=None, setpoint_target_c=None):
        sp = None
        if setpoint_current_c is not None and setpoint_target_c is not None:
            sp = {"current_c": setpoint_current_c, "target_c": setpoint_target_c}
        return EA.scenarios(appliances, bill, sp)

    def t_search(query):
        hits = EA.retrieve(query)
        sources.extend(h["url"] for h in hits if h["url"])
        return hits

    dispatch = {"compute_bill": t_compute, "appliance_energy": t_appliance, "search_official_docs": t_search,
                "sun_on_facade": tool_sun_on_facade}
    ctx = {"bill": bill or "not provided", "verification": _round(_slim(verification)) if verification else "not run"}
    msgs = [{"role": "system", "content": BILL_SYSTEM + "\n\nBILL CONTEXT (verified by the user):\n" +
             json.dumps(ctx, ensure_ascii=False, default=str)}] + messages
    backend_idx = 0
    for _ in range(max_steps):
        backend_idx, resp = _completion(msgs, backend_idx, BILL_TOOLS, timeout)
        m = resp.choices[0].message
        if not m.tool_calls:
            msgs.append({"role": "assistant", "content": m.content})
            return m.content, msgs[1:], sorted(set(sources))
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [tc.model_dump() for tc in m.tool_calls]})
        for tc in m.tool_calls:
            try:
                result = dispatch[tc.function.name](**json.loads(tc.function.arguments or "{}"))
            except Exception as e:
                result = {"error": str(e)}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(_round(result), default=str)})
    return "Sorry, I could not finish. Please rephrase your question.", msgs[1:], sorted(set(sources))


def _slim(v):
    """Verification without bulky fields, for the prompt."""
    keep = ("status", "summary", "checks", "causes", "warnings")
    out = {k: v.get(k) for k in keep if k in v}
    calc = v.get("calculation") or {}
    out["calculation"] = {k: calc.get(k) for k in ("status", "lines", "monthly_kwh", "band", "vat_rate", "category",
                                                    "assumptions", "reason") if k in calc}
    return out
