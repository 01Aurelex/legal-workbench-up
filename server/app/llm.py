# -*- coding: utf-8 -*-
"""本地大模型适配层（默认 Ollama，兼容 /api/tags、/api/chat）。
严格模式：问题先在【本地法律库】检索，模型只能依据检索到的法条原文回答并标注来源；
未运行本地模型时进入“纯检索演示模式”，保证预览版可离线验证全流程。"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from datetime import datetime

from .config import load_config
from . import lawlib, db

# 面向不同显存的本地部署推荐（Qwen3 系列中文与法律文本表现均衡、可商用）
RECOMMENDED = [
    {"model": "qwen3:8b",  "vram": "8GB 显存/32GB 内存可跑 Q4 量化", "scene": "普通办公电脑，流畅首选"},
    {"model": "qwen3:14b", "vram": "12-16GB 显存", "scene": "法律文书理解与说理质量更均衡（推荐主力）"},
    {"model": "qwen3:32b", "vram": "24GB 显存（4090/3090）", "scene": "复杂案件分析，质量优先"},
    {"model": "deepseek-r1:14b", "vram": "16GB 显存", "scene": "需要深度推理的案件策略分析（备选）"},
]

STRICT_PROMPT = (
    "你是律师本地工作台的法律检索助手。必须严格遵守：\n"
    "1. 只能依据下面【本地法律库摘录】中的原文回答，不得使用摘录之外的任何知识、记忆或推测；\n"
    "2. 每个结论后用括号标注来源，格式（来源：法律名称 第X条）；\n"
    "3. 摘录中找不到依据时，必须明确回答“本地法律库中未检索到相关依据，建议补充法律库后再问”，不得编造法条；\n"
    "4. 回答使用简体中文，结构清晰，先结论后依据，最后给律师行动提示。\n\n"
    "【本地法律库摘录】\n{context}\n\n【用户问题】{question}")


def _req(method: str, url: str, payload: dict | None = None, timeout: float = 8.0):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def status() -> dict:
    cfg = load_config()["llm"]
    info = {"reachable": False, "installed": [], "configured": cfg["model"],
            "provider": cfg["provider"], "base_url": cfg["base_url"],
            "recommended": RECOMMENDED, "error": ""}
    try:
        if cfg.get("provider") in ("bundled", "openai"):
            # OpenAI 兼容：llama.cpp / LM Studio / vLLM
            r = _req("GET", f"{cfg['base_url'].rstrip('/')}/models", timeout=3.0)
            info["reachable"] = True
            info["installed"] = [m.get("id") for m in r.get("data", [])]
        else:
            tags = _req("GET", f"{cfg['base_url']}/api/tags", timeout=3.0)
            info["reachable"] = True
            info["installed"] = [m.get("name") for m in tags.get("models", [])]
    except Exception as e:
        info["error"] = f"未连接到本地模型运行时（{type(e).__name__}），当前可使用纯检索演示模式"
    return info


def chat(messages: list[dict], model: str | None = None, timeout: float = 120.0) -> str:
    cfg = load_config()["llm"]
    use_openai = cfg.get("provider") in ("bundled", "openai")
    if use_openai:
        payload = {"model": model or cfg["model"], "messages": messages,
                   "temperature": cfg.get("temperature", 0.2), "stream": False}
        r = _req("POST", f"{cfg['base_url'].rstrip('/')}/chat/completions", payload, timeout=timeout)
        return (r.get("choices") or [{}])[0].get("message", {}).get("content", "")
    payload = {"model": model or cfg["model"], "messages": messages,
               "stream": False, "options": {"temperature": cfg.get("temperature", 0.2)}}
    r = _req("POST", f"{cfg['base_url']}/api/chat", payload, timeout=timeout)
    return (r.get("message") or {}).get("content", "")


def grounded_answer(question: str) -> dict:
    evidence = lawlib.retrieve(question, top_k=6)
    context = "\n\n".join(f"[{e['law']}·{e['article']}] {e['text']}" for e in evidence)
    st = status()
    if not evidence:
        return {"mode": "无依据", "answer": "本地法律库中未检索到相关依据，请先在“法律库”目录补充现行有效的法律法规文本并重建索引。",
                "evidence": [], "model_status": st}
    prompt = STRICT_PROMPT.format(context=context, question=question)
    if st["reachable"]:
        try:
            answer = chat([{"role": "user", "content": prompt}])
            mode = "本地大模型+本地法律库"
        except Exception as e:
            answer, mode = _demo_answer(evidence, str(e)), "纯检索演示模式(模型调用失败)"
    else:
        answer, mode = _demo_answer(evidence, ""), "纯检索演示模式(未检测到本地模型)"
    db.audit("AI查询", f"{mode}：{question[:40]}")
    return {"mode": mode, "answer": answer, "evidence": evidence, "model_status": st}


def _demo_answer(evidence: list[dict], err: str) -> str:
    lines = ["【纯检索演示模式】尚未连接本地大模型，以下为本地法律库匹配到的法条原文，供直接引用："]
    for e in evidence:
        lines.append(f"\n● {e['law']} {e['article']}：{e['text'][:300]}")
    lines.append("\n安装并启动 Ollama、拉取推荐模型后，此处将由本地大模型严格依据上述法条生成结论与行动提示。")
    if err:
        lines.append(f"（模型错误：{err[:80]}）")
    return "\n".join(lines)


def version_check() -> dict:
    """需求14：比对本地已安装模型与推荐清单，给出更新/功能提示。"""
    st = status()
    hints = []
    installed = set(st["installed"])
    if not st["reachable"]:
        hints.append("未检测到 Ollama 服务：安装后执行 ollama serve，并在设置中确认地址。")
    else:
        if not installed:
            hints.append("本地尚无模型，建议按硬件选择执行 ollama pull qwen3:14b（或 8b）。")
        for rec in RECOMMENDED:
            if any(rec["model"].split(":")[0] in x for x in installed):
                hints.append(f"已安装 {rec['model']} 系列，可通过 ollama pull {rec['model']} 检查更新到最新量化版本。")
        if st["configured"] not in installed and installed:
            hints.append(f"当前默认模型 {st['configured']} 未安装，请在设置中切换为已安装模型或拉取它。")
    return {"checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "installed": sorted(installed), "recommended": RECOMMENDED, "hints": hints}
