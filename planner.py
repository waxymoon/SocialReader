# -*- coding: utf-8 -*-
"""美食情报采集 Agent —— 决策循环骨架（v0，2026-09-07）

架构铁律：
- 模型只输出「决定」，代码只执行「行动」并校验决定；模型永远碰不到浏览器/文件。
- 动作白名单：search / deep / wrapup / ask（无自由发挥）。
- 观察结果 = 代码跑出来的真实数字，禁止模型编造；沿用任务书「不虚构抓取结果」。
- 终止条件硬编码：轮数上限；wrapup 需满足最低目标，不足打回一次。
- 人在回路：ask 或连续无进展时停住等输入。

大脑默认 DeepSeek deepseek-v4-flash（妹妹拍板：GLM 免费太慢影响演示）；
已知 v4-flash 偶发空 content（实测），内置重试 + deepseek-chat 兜底。

用法：
  python planner.py --goal "找 2 个有活人感的黄焖鸡新品话题" [--rounds 4] [--mode live|demo]
    live: 工具=真实只读扫描（scan_local）
    demo: 工具=标注 SIMULATED 的假采集（仅跑通循环演示，绝不冒充真实抓取）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

try:
    import urllib.request
except ImportError:  # pragma: no cover
    pass

ENV_FILE = Path(r"D:\Hermes-Agent\.env")
DS_API_URL = "https://api.deepseek.com/chat/completions"
DS_MODEL_PRIMARY = "deepseek-v4-flash"   # 妹妹拍板：快
DS_MODEL_FALLBACK = "deepseek-chat"      # 实测稳定兜底

ACTIONS = ("search", "deep", "wrapup", "ask")

SYSTEM_PROMPT = """你是「美食情报采集 Agent」的决策大脑。你的工作：根据用户目标和当前采集状态，每一步只从四个动作里选一个，并给出简短理由。

动作定义：
- search: 换一个或新开一个关键词去搜索采集。必须给 next_query（具体搜索词，像真实用户会搜的，可带"新品/测评/隐藏吃法"等词）。
- deep: 对已有内容继续深挖（同话题再加量）。
- wrapup: 认为已达成目标，收工并产出知识库。
- ask: 拿不准、信息不足或连续没有进展时，停下来向用户提问。

规则：
1. 只输出一个 JSON 对象，格式：{"action": "search|deep|wrapup|ask", "next_query": "关键词(仅search需要)", "reason": "一句话理由"}
2. 不要输出 JSON 以外的任何文字、markdown 或解释。
3. 不许编造采集结果——你只能基于状态快照里给出的真实数字做判断。
4. wrapup 前先核对：状态里「已采集内容数」是否达到目标要求条数（见目标要求行）？不足时不要 wrapup，优先 search 换词补采。
5. 连续失败或没进展时，诚实选 ask，不要假装成功。"""


def load_deepseek_key() -> str:
    value = os.environ.get("DEEPSEEK_API_KEY", "")
    if value:
        return value.strip()
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("DEEPSEEK_API_KEY 未配置（环境变量或 D:\\Hermes-Agent\\.env）")


def ds_chat(prompt: str, temperature: float = 0.2, max_tokens: int = 600) -> dict[str, Any]:
    """调 DeepSeek 返回 JSON 对象。v4-flash 空 content 重试 → deepseek-chat 兜底。"""
    key = load_deepseek_key()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    last_err: Exception | None = None
    models = [DS_MODEL_PRIMARY, DS_MODEL_PRIMARY, DS_MODEL_FALLBACK]  # 主模型试2次→兜底
    for model in models:
        for attempt in range(2):
            payload = json.dumps({
                "model": model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }).encode("utf-8")
            try:
                req = urllib.request.Request(
                    DS_API_URL, data=payload,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    content = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise ValueError("空 content（v4-flash 已知偶发）")
                cleaned = re.sub(r"^```json\s*", "", content.strip())
                cleaned = re.sub(r"\s*```$", "", cleaned)
                obj = json.loads(cleaned)
                if isinstance(obj, dict):
                    return obj
                raise ValueError("非对象 JSON")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"DeepSeek 调用失败：{last_err}")


# ---------- 工具层：真实只读扫描（live） ----------
CONTENT_ROOT = Path(r"D:\ObsidianVault\采集\内容流水线")
PYTHON_EXE = os.environ.get("SOCIALREADER_PYTHON", r"D:\Python312\python.exe")
ROOT_DIR = Path(__file__).resolve().parent
PIPELINE = ROOT_DIR / "pipeline_capture.py"

class LoginRequiredError(RuntimeError):
    """调试浏览器登录态缺失：由循环转 ask（人在回路），不伪造结果。"""


def scan_local(query: str) -> dict[str, Any]:
    """真实只读：扫描本地已采集目录（内容流水线/<query>），返回客观数字。"""
    q = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(query or "")).strip().strip(" .")
    directory = CONTENT_ROOT / q
    if not directory.is_dir():
        return {"found_posts": 0, "rule_pass_expressions": 0, "local_posts": [], "note": f"本地无「{query}」目录，需真实采集"}
    mds = [p for p in sorted(directory.glob("*.md")) if p.name != "_汇总.md"]
    posts = []
    rule_pass = 0
    for md in mds:
        text = md.read_text(encoding="utf-8", errors="replace")
        fm = text.split("---", 2)
        title = ""
        if len(fm) >= 3:
            m = re.search(r"(?m)^title:\s*(.+)$", fm[1])
            title = m.group(1).strip() if m else ""
        posts.append({"file": md.name, "title": title[:40]})
    return {"found_posts": len(posts), "rule_pass_expressions": rule_pass,
            "local_posts": posts, "note": "本地真实归档（只读扫描）"}


def mock_capture(query: str) -> dict[str, Any]:
    """【SIMULATED·仅 demo】假采集：只用于跑通循环逻辑，返回数据明确标注模拟。"""
    hits = len(re.findall(r"[\u4e00-\u9fff]", query))
    found = min(3, max(1, hits // 3 + 1))
    rule_pass = found if "活人感" not in query else found - 1  # 随便一个可读信号
    return {"found_posts": found, "rule_pass_expressions": rule_pass,
            "local_posts": [], "note": "SIMULATED 模拟数据（demo 模式，非真实抓取）"}


# ---------- 工具层：真实采集（real 模式） ----------
def _confirm_login(proc) -> None:
    """login_gate 的人回车确认：启动后自动回一个回车放行（登录态在 profile）。"""
    try:
        if proc.poll() is None:
            proc.stdin.write("\n")
            proc.stdin.flush()
    except Exception:
        pass



def agent_capture(query: str, maximum: int = 3, content_type: str = "image", timeout: int = 420) -> dict[str, Any]:
    """真采集一轮：子进程跑 pipeline_capture.py 小红书。图文优先=快，无 ASR 等待。

    返回客观数字（成功/失败）。登录态缺失抛 LoginRequiredError（循环转 ask）。
    沿用 pipeline 自身低频防反爬；绝不虚构抓取结果。
    """
    if not PIPELINE.is_file():
        return {"found_posts": 0, "rule_pass_expressions": 0, "local_posts": [], "note": "pipeline_capture.py 不存在"}
    safe_q = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", query.strip()).strip(" .") or "未命名"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONUTF8"] = "1"
    cmd = [str(PYTHON_EXE), "-u", str(PIPELINE), "xhs", query, "--max", str(maximum),
           "--content-type", content_type, "--asr-model", "tiny"]
    try:
        proc = __import__("subprocess").Popen(
            cmd, cwd=str(ROOT_DIR), env=env, stdin=__import__("subprocess").PIPE,
            stdout=__import__("subprocess").PIPE, stderr=__import__("subprocess").STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
    except Exception as exc:  # noqa: BLE001
        return {"found_posts": 0, "rule_pass_expressions": 0, "local_posts": [], "note": f"启动采集失败：{exc}"}
    # pipeline 每次启动都停在 login_gate 等人回车（web 端"我已登录，继续"同款）——
    # 登录态在 profile 里则直接回车放行；真未登录会体现在后续"成功 0 条+失败原因"里，由 Agent 观察决定。
    logs: list[str] = []
    try:
        __import__("threading").Timer(3.0, _confirm_login, args=(proc,)).start()
        for line in proc.stdout:
            logs.append(line.rstrip())
        proc.wait(timeout=timeout)
    except __import__("subprocess").TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        return {"found_posts": 0, "rule_pass_expressions": 0, "local_posts": [], "note": f"采集超时(>{timeout}s)：词「{query}」跳过"}
    text = "\n".join(logs[-300:])
    success = len(re.findall(r"\[已写入\]", text))
    failed = len(re.findall(r"\[单条失败", text))
    return {"found_posts": success, "rule_pass_expressions": 0,
            "local_posts": [], "note": f"真实采集「{query}」成功 {success} 条 / 失败 {failed} 条"}


def analyze_local_dir(query: str) -> dict[str, Any]:
    """分析指定关键词目录 → 返回客观数字（food_v1 规则 pass 活人感句数/卡数）。"""
    from domain_pipeline import load_analysis_items, run_analysis  # noqa: PLC0415
    from food_metrics import read_jsonl  # noqa: PLC0415

    q = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", query.strip()).strip(" .")
    directory = CONTENT_ROOT / q
    if not directory.is_dir():
        return {"found_posts": 0, "rule_pass_expressions": 0, "local_posts": [], "note": f"目录不存在「{q}」"}
    items = load_analysis_items(directory, include_fixtures=False, limit=10)
    if not items:
        return {"found_posts": 0, "rule_pass_expressions": 0, "local_posts": [], "note": "该目录无有效内容可分析"}
    out = run_analysis(items)
    cards = read_jsonl(out / "food_cards.jsonl")
    passed = sum(1 for c in cards for e in c.get("evidences", []) if e.get("rule_review_status") == "pass")
    posts = [{"file": str(c.get("title") or "")[:40], "title": ""} for c in cards]
    return {"found_posts": len(cards), "rule_pass_expressions": passed,
            "local_posts": posts, "note": f"真实分析 {len(cards)} 卡 / 规则活人感 pass {passed} 句"}


def _cli_ask(question: str) -> str | None:
    """CLI 默认问答：普通问题走 input；__prompt_query__ 让用户给搜索词；
    __login_ready__ 等登录回车。EOF（管道/后台）返回 None=放弃。"""
    try:
        if question == "__prompt_query__":
            return input("请输入要搜的关键词（回车放弃）：").strip()
        if question == "__login_ready__":
            input("登录完成后按回车让 Agent 重试本轮：")
            return "ok"
        return input("🤖 Agent 提问：" + question + "\n你的回答（回车=让 Agent 自己定）：").strip()
    except EOFError:
        return None


def parse_goal_number(goal: str) -> int:
    """从目标里解析期望数量（如"找 2 个"→2）。无数字→1，上限 20。"""
    m = re.search(r"(\d+)", goal or "")
    n = int(m.group(1)) if m else 1
    return max(1, min(n, 20))


# ---------- 决策循环 ----------
def build_state_prompt(goal: str, state: dict[str, Any], round_no: int, max_rounds: int,
                    target: int | None = None) -> str:
    target = target if target is not None else parse_goal_number(goal)
    samples = state.get("samples", [])
    sample_lines = "\n".join(f"  - {s}" for s in samples[-6:]) if samples else "  （暂无）"
    return f"""用户目标：{goal}
当前轮次：{round_no}/{max_rounds}
目标要求：至少 {target} 条合格内容（已获 {state.get('found_posts', 0)} 条，还差 {max(0, target - state.get('found_posts', 0))} 条）
本轮状态快照（全部为真实数字）：
- 已采集内容数：{state.get('found_posts', 0)}
- 已获得活人感表达（规则+语义通过）：{state.get('rule_pass_expressions', 0)}
- 最近一次失败/提示：{state.get('last_error') or '无'}
- 最近采集/扫描到的内容：\n{sample_lines}

请输出你的下一步决定（JSON）。"""


def validate_decision(raw: dict[str, Any], state: dict[str, Any], goal_note: str) -> dict[str, Any]:
    """校验层：白名单/字段/安全。非法决定强制 ask。"""
    action = str(raw.get("action") or "").strip()
    if action not in ACTIONS:
        return {"action": "ask", "next_query": "", "reason": f"非法动作 {action!r}，改为询问用户"}
    decision = {"action": action, "next_query": str(raw.get("next_query") or "").strip(), "reason": str(raw.get("reason") or "")[:200]}
    if action == "search":
        if not decision["next_query"]:
            return {"action": "ask", "next_query": "", "reason": "search 缺少 next_query"}
        if len(decision["next_query"]) > 60 or re.search(r"[<>:\"/\\|?*\x00-\x1f]", decision["next_query"]):
            return {"action": "ask", "next_query": "", "reason": "next_query 非法字符或过长"}
        if decision["next_query"] in state.get("used_queries", []):
            return {"action": "search", "next_query": decision["next_query"] + " 新品",
                    "reason": "该词已采过，自动补限定词重试"}
    return decision


def run_loop(goal: str, max_rounds: int = 4, mode: str = "live", real_max: int = 3,
            content_type: str = "image", ask_fn=None,
            on_log=None) -> dict[str, Any]:
    if ask_fn is None:
        ask_fn = _cli_ask
    if on_log is None:
        on_log = print
    if mode == "real":
        tool: Callable[[str], dict[str, Any]] | None = None  # 双阶段：agent_capture + analyze_local_dir
    else:
        tools: dict[str, Callable[[str], dict[str, Any]]] = {
            "live": scan_local, "demo": mock_capture,
        }
        if mode not in tools:
            raise ValueError("mode 必须为 live / demo / real")
        tool = tools[mode]
    state: dict[str, Any] = {"found_posts": 0, "rule_pass_expressions": 0,
                             "last_error": "", "samples": [], "used_queries": [], "rounds": []}
    goal_note = re.sub(r"\d+", lambda m: "数字目标", goal)  # 防 prompt 注入式诱导（占位）

    for round_no in range(1, max_rounds + 1):
        on_log(f"\n===== 第 {round_no}/{max_rounds} 轮 =====")
        # Think
        prompt = build_state_prompt(goal, state, round_no, max_rounds,
                                 target=parse_goal_number(goal))
        raw = ds_chat(prompt)
        decision = validate_decision(raw, state, goal_note)
        on_log(f"[Think] action={decision['action']} query={decision['next_query'] or '—'} 理由={decision['reason']}")

        # Act
        if decision["action"] == "ask":
            answer = ask_fn(decision["reason"])
            if answer is None:  # 非交互/用户放弃：收工
                on_log("[无应答] ask 无应答，按收工处理")
                break
            if not answer.strip():
                decision = {"action": "search", "next_query": ask_fn("__prompt_query__"), "reason": "人工指定"}
            else:
                state["last_human"] = answer
                on_log(f"[人] {answer}（已记入状态，继续下一轮）")
                state["rounds"].append({"round": round_no, "action": "ask", "human": answer})
                continue

        if decision["action"] == "wrapup":
            # 达标校验：解析目标数 N，已获内容不足 N 且轮数未尽 → 打回重决策（不喊假完成）
            target = parse_goal_number(goal)
            if state["found_posts"] < target and round_no < max_rounds:
                on_log(f"[校验] wrapup 被拒：目标 {target} 条，当前仅 {state['found_posts']} 条，下一轮继续补采")
                state["rounds"].append({"round": round_no, "action": "wrapup_rejected",
                                        "query": "", "reason": decision["reason"]})
                continue
            state["rounds"].append({"round": round_no, "action": "wrapup",
                                    "query": "", "reason": decision["reason"]})
            on_log("[收工] 达成收工条件")
            break

        # 执行工具
        query = decision.get("next_query") or ""
        if query:
            if query in state["used_queries"]:
                on_log("[执行] 关键词重复，跳过本轮")
                state["rounds"].append({"round": round_no, "action": "skip", "reason": "重复词"})
                continue
            state["used_queries"].append(query)
        try:
            if mode == "real":
                cap = agent_capture(query, maximum=real_max, content_type=content_type)
                if cap.get("note", "").startswith("真实采集"):
                    analyzed = analyze_local_dir(query)
                    obs = dict(analyzed)
                    obs["note"] = cap["note"] + " → " + analyzed["note"]
                else:
                    obs = cap
            else:
                obs = tool(query) if query else {"found_posts": 0, "rule_pass_expressions": 0, "note": "无关键词"}
        except LoginRequiredError as exc:
            on_log(f"[登录] {exc}")
            try:
                answer = ask_fn("__login_ready__")
            except Exception:
                answer = None
            if answer is None:
                on_log("[无交互] 登录未就绪，本轮放弃")
                state["last_error"] = str(exc)
                state["rounds"].append({"round": round_no, "action": "login_wait", "query": query,
                                        "reason": str(exc)})
                continue
            state["last_error"] = "登录后重试"
            state["rounds"].append({"round": round_no, "action": "login_wait", "query": query,
                                    "reason": "等待人工登录"})
            continue  # 下一轮重新 Think（登录后状态未变，模型会再决定）
        except Exception as exc:  # noqa: BLE001
            obs = {"found_posts": 0, "rule_pass_expressions": 0, "note": f"工具异常 {exc}"}
        # Observe
        state["found_posts"] += int(obs.get("found_posts") or 0)
        state["rule_pass_expressions"] += int(obs.get("rule_pass_expressions") or 0)
        state["last_error"] = obs.get("note") or ""
        for p in obs.get("local_posts") or []:
            state["samples"].append(f"{p.get('file', '')}｜{p.get('title', '')}")
        on_log(f"[Act/Observe] {obs.get('note')} → 累计内容 {state['found_posts']}，活人感表达 {state['rule_pass_expressions']}")
        state["rounds"].append({"round": round_no, "action": decision["action"],
                                "query": query, "reason": decision["reason"],
                                "observation": obs.get("note", "")})

    print("\n===== 循环结束 =====")
    print(f"累计：内容 {state['found_posts']} 条 / 活人感表达 {state['rule_pass_expressions']} 条 / 用词 {state['used_queries']}")
    return state


class AgentSession:
    """页面 Agent 会话：后台线程跑决策循环；ask 挂起等待人工回复（Event 同步）；
    日志进 self.logs 供轮询；超时/停止可终止。"""

    def __init__(self, goal: str, max_rounds: int = 4, mode: str = "real",
                 real_max: int = 3, content_type: str = "image"):
        self.goal = goal
        self.max_rounds = max_rounds
        self.mode = mode
        self.real_max = real_max
        self.content_type = content_type
        self.logs: list[str] = []
        self.state = "idle"          # idle|running|awaiting_input|done|stopped|error
        self.pending_question = ""
        self.answer_text = ""
        self.state_dict: dict[str, Any] = {}
        self._event = __import__("threading").Event()
        self._stop = False
        self._thread = None

    def _log(self, text: str) -> None:
        self.logs.append(str(text))
        if len(self.logs) > 500:
            self.logs = self.logs[-400:]

    def _ask(self, question: str) -> str | None:
        if self._stop:
            return None
        self.pending_question = question
        self.state = "awaiting_input"
        self._event.clear()
        self._event.wait(timeout=900)  # 15 分钟无回复按放弃
        if not self._event.is_set():
            self.state = "error"
            self._log("[超时] 等待人工回复超时，会话结束")
            return None
        return self.answer_text

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Agent 已在运行")
        self.logs = []
        self.state = "running"
        self._stop = False
        self._thread = __import__("threading").Thread(
            target=self._run, daemon=True, name="agent-session")
        self._thread.start()

    def _run(self) -> None:
        try:
            self.state_dict = run_loop(
                self.goal, self.max_rounds, self.mode,
                real_max=self.real_max, content_type=self.content_type,
                ask_fn=self._ask, on_log=self._log)
            if self.state != "error":
                self.state = "done"
            self._log(f"[完成] 累计：内容 {self.state_dict.get('found_posts', 0)} 条 / "
                      f"活人感表达 {self.state_dict.get('rule_pass_expressions', 0)} 条")
        except Exception as exc:  # noqa: BLE001
            self.state = "error"
            self._log(f"[错误] {type(exc).__name__}: {exc}")

    def answer(self, text: str) -> None:
        self.answer_text = str(text or "").strip()
        self.pending_question = ""
        self._event.set()

    def stop(self) -> None:
        self._stop = True
        self._event.set()

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "goal": self.goal,
            "mode": self.mode,
            "logs": self.logs[-200:],
            "pending_question": self.pending_question,
            "stats": self.state_dict,
        }


AGENT_SESSION: AgentSession | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="美食情报采集 Agent（决策循环骨架）")
    parser.add_argument("--goal", default="找 2 个有活人感的黄焖鸡新品话题", help="用户目标")
    parser.add_argument("--rounds", type=int, default=4, help="最大轮数")
    parser.add_argument("--mode", choices=("live", "demo", "real"), default="demo",
                        help="real=真实采集小红书 / live=本地只读扫描 / demo=模拟数据")
    parser.add_argument("--real-max", type=int, default=3, help="real 模式每轮采集条数(1-5，防风控)")
    parser.add_argument("--content-type", choices=("all", "image", "video"), default="image",
                        help="real 模式内容类型（默认 image=图文快，无 ASR 等待）")
    args = parser.parse_args()
    if args.rounds < 1 or args.rounds > 8:
        print("轮数必须在 1–8")
        return 2
    if args.real_max < 1 or args.real_max > 5:
        print("real 模式每轮采集 1–5 条（低频防风控）")
        return 2
    run_loop(args.goal, args.rounds, args.mode, real_max=args.real_max, content_type=args.content_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
