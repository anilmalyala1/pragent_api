# app/agents/review_agent.py
import os
import asyncio
import operator
from typing import Annotated, Dict, List, Optional, Set, TypedDict

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.services.file_service import FileService
from app.model.review import Issue
from dotenv import load_dotenv,find_dotenv

load_dotenv(find_dotenv(),override=True)

class EmitIssuesArgs(BaseModel):
    """Schema for LLM output - must contain 'type': 'object'"""
    issues: List[Issue] = Field(default_factory=list)

# ------------------ Config / Guardrails ------------------
MAX_FILES = int(os.getenv("REVIEW_MAX_FILES", "20"))
MAX_CONCURRENCY = int(os.getenv("REVIEW_CONCURRENCY", "4"))
LLM_TIMEOUT = float(os.getenv("REVIEW_TIMEOUT_SECS", "30"))
LLM_RETRIES = int(os.getenv("REVIEW_RETRIES", "2"))
ONLY_CHANGED_DEFAULT = os.getenv("REVIEW_ONLY_CHANGED", "true").lower() == "true"
INCLUDE_STATIC_DEFAULT = os.getenv("REVIEW_INCLUDE_STATIC", "true").lower() == "true"

# ------------------ LLM (Gemini via OpenAI-compatible endpoint) ------------------
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

llm = ChatOpenAI(
    base_url=GEMINI_BASE_URL,
    api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
    model=GEMINI_MODEL,
    temperature=0,
    max_tokens=1200
)

SYSTEM = """You are a senior code reviewer. Output ONLY JSON that matches the schema.
Focus your analysis on the lines the user marks as CHANGED_LINES when provided.
Findings rules:
- Severity: critical | major | minor
- Category: security | quality | performance | best_practice
- Keep each description concise (1–2 lines).
- Provide minimal patch "before" and "after" when a fix is clear.
"""
FILE_TMPL = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human",
     "File: {file}\n"
     "Head SHA: {sha}\n"
     "{changed_hint}\n"
     "Code:\n```\n{code}\n```\n"
     "Return JSON with key 'issues' matching the Issue[] schema.")
])

# Structured output schema
class IssuesOut(BaseModel):
    issues: List[Issue] = Field(default_factory=list)



# ------------------ Graph State ------------------
class ReviewState(TypedDict, total=False):
    # request
    owner: str
    repo: str
    number: int
    paths: Optional[List[str]]
    only_changed: bool
    include_static: bool

    # fetched
    headSha: str
    files: List[str]
    contents: Dict[str, str]
    changed: Dict[str, Set[int]]  # filename -> changed line numbers

    # accumulated results
    issues: Annotated[List[Issue], operator.add]
    summary: str

# ------------------ Helpers ------------------
def filter_code_files(files: List[str]) -> List[str]:
    exts = {".py",".ts",".tsx",".js",".jsx",".go",".rs",".java",".kt",".swift",".rb",".php",".c",".h",".cpp",".hpp",".cs",".ipynb",".sh",".yaml",".yml",".toml",".json"}
    keep = [f for f in files if any(f.lower().endswith(e) for e in exts)]
    return keep or files

def human_summary(issues: List[Issue]) -> str:
    if not issues:
        return "No issues found."
    sev_rank = {"critical": 0, "major": 1, "minor": 2}
    counts = {"critical":0,"major":0,"minor":0}
    by_cat = {"security":0,"quality":0,"performance":0,"best_practice":0}
    for i in issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1
        by_cat[i.category] = by_cat.get(i.category, 0) + 1
    total = len(issues)
    top = sorted(issues, key=lambda x: (sev_rank.get(x.severity, 9), x.line or 1))[:3]
    bullets = "; ".join([f"{i.severity} in {i.file}:{i.line or '-'} — {i.title}" for i in top])
    return (
        f"{total} findings "
        f"(critical {counts['critical']}, major {counts['major']}, minor {counts['minor']}); "
        f"by category: sec {by_cat['security']}, quality {by_cat['quality']}, perf {by_cat['performance']}, best {by_cat['best_practice']}. "
        f"Top: {bullets}"
    )

async def with_retries(coro_factory, retries: int = LLM_RETRIES):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=LLM_TIMEOUT)
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_exc

# ------------------ Static checks (lightweight heuristics for Python) ------------------
def static_checks_python(file: str, code: str, changed: Optional[Set[int]]) -> List[Issue]:
    issues: List[Issue] = []
    lines = code.splitlines()
    def add(line, title, desc, severity="major", category="best_practice", before=None, after=None):
        issues.append(Issue(
            id=f"ST-{file}-{line}-{len(issues)+1}",
            file=file,
            line=line,
            title=title,
            description=desc,
            severity=severity,
            category=category,
            patch=(dict(before=before, after=after) if before is not None and after is not None else None)  # type: ignore
        ))

    line_iter = enumerate(lines, start=1)
    for ln, text in line_iter:
        if changed and ln not in changed:
            continue
        t = text.strip()

        # dangerous eval/exec
        if "eval(" in t:
            add(ln, "Avoid eval()", "Use safe parsing/AST or explicit mapping.", "critical", "security")
        if "exec(" in t:
            add(ln, "Avoid exec()", "Refactor to functions or plugins; exec is dangerous.", "critical", "security")
        # subprocess shell=True
        if "subprocess" in t and "shell=True" in t:
            add(ln, "Subprocess with shell=True", "Avoid shell=True to reduce injection risk.", "major", "security")
        # requests verify=False
        if "requests." in t and "verify=False" in t:
            add(ln, "TLS verification disabled", "Do not disable certificate verification.", "critical", "security")
        # broad except
        if t.startswith("except:"):
            add(ln, "Broad exception handler", "Catch specific exceptions or re-raise.", "minor", "quality")
        # hard-coded secrets pattern (naive)
        if "API_KEY" in t or "SECRET" in t:
            add(ln, "Potential hard-coded secret", "Read from env/secret manager, not source code.", "major", "security")

    return issues

# ------------------ Nodes ------------------
async def fetch_node(state: ReviewState, filesvc: FileService) -> ReviewState:
    # contents at head SHA
    fc = await filesvc.get_pr_files_and_contents(state["owner"], state["repo"], state["number"], state.get("paths"))
    head, files, contents = fc["headSha"], filter_code_files(fc["files"]), fc["contents"]
    # changed lines map
    changed = await filesvc.get_pr_changed_lines(state["owner"], state["repo"], state["number"])
    # keep only changed lines for kept files
    changed = {f: changed.get(f, set()) for f in files}
    return {"headSha": head, "files": files[:MAX_FILES], "contents": contents, "changed": changed}

async def static_node(state: ReviewState) -> ReviewState:
    if not state.get("include_static", INCLUDE_STATIC_DEFAULT):
        return {"issues": []}
    out: List[Issue] = []
    for f in state.get("files", []):
        code = (state.get("contents", {}) or {}).get(f, "")
        if not code or not f.lower().endswith(".py"):
            continue
        out.extend(static_checks_python(f, code, state.get("changed", {}).get(f)))
    return {"issues": out}

async def review_node(state: ReviewState) -> ReviewState:
    files = state.get("files", [])
    contents = state.get("contents", {})
    sha = state.get("headSha", "")
    only_changed = state.get("only_changed", ONLY_CHANGED_DEFAULT)

    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def review_file(f: str):
        text = contents.get(f, "")
        if not text:
            return []
        changed = state.get("changed", {}).get(f) or set()
        changed_hint = ""
        if only_changed and changed:
            # Provide concise hint to focus the LLM
            rng = sorted(changed)
            preview = ", ".join(map(str, rng[:30]))
            changed_hint = f"CHANGED_LINES: {preview}\nFocus your review on these lines and their immediate context."

        chain = FILE_TMPL | llm.with_structured_output(IssuesOut)

        async def call():
            return await chain.ainvoke({"file": f, "sha": sha, "code": text, "changed_hint": changed_hint})

        async with sem:
            out: IssuesOut = await with_retries(call)
            # If only_changed: filter any issues that come back on untouched lines
            if only_changed and changed:
                filtered = [i for i in out.issues if (i.line or 0) in changed]
                return filtered
            return out.issues

    per_file = await asyncio.gather(*[review_file(f) for f in files])
    flat: List[Issue] = []
    for lst in per_file:
        flat.extend(lst or [])
    return {"issues": flat}

def dedupe_node(state: ReviewState) -> ReviewState:
    seen = set()
    uniq: List[Issue] = []
    for i in state.get("issues", []):
        key = (i.file, i.line or 0, i.title.strip().lower())
        if key not in seen:
            seen.add(key)
            uniq.append(i)
    return {"issues": uniq}

def summarize_node(state: ReviewState) -> ReviewState:
    return {"summary": human_summary(state.get("issues", []))}

# ------------------ Builder ------------------
def build_review_graph(filesvc: FileService):
    graph = StateGraph(ReviewState)

    async def _fetch(s: ReviewState):     return await fetch_node(s, filesvc)
    graph.add_node("fetch", _fetch)
    graph.add_node("static", static_node)
    graph.add_node("review", review_node)
    graph.add_node("dedupe", dedupe_node)
    graph.add_node("summarize", summarize_node)

    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "static")
    graph.add_edge("static", "review")
    graph.add_edge("review", "dedupe")
    graph.add_edge("dedupe", "summarize")
    graph.add_edge("summarize", END)

    # ✅ Checkpointer to resume/replay
    #checkpointer = MemorySaver()
    #return graph.compile(checkpointer=checkpointer)
    return graph.compile()