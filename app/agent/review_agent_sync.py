# app/agents/review_agent_sync.py
import os
import re
import json
import time
import requests
import functools
from typing import Dict, List, Optional, Set, Tuple, Literal, Any

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain.output_parsers.json import SimpleJsonOutputParser

# Rate limiting using the ratelimit library
try:
    from ratelimit import limits, sleep_and_retry
    RATE_LIMIT_AVAILABLE = True
except ImportError:
    print("Warning: ratelimit library not installed. Install with: pip install ratelimit")
    RATE_LIMIT_AVAILABLE = False
    
    # Fallback decorator if ratelimit is not available
    def limits(calls=None, period=None):
        def decorator(func):
            return func
        return decorator
    
    def sleep_and_retry(func):
        return func


# =========================
# Models (UI contract)
# =========================
class IssuePatch(BaseModel):
    before: str = Field(..., description="Original code snippet to replace")
    after: str = Field(..., description="Suggested replacement snippet")

class Issue(BaseModel):
    id: str
    file: str
    line: Optional[int] = None
    title: str
    description: str
    severity: Literal["critical", "major", "minor"]
    category: Literal["security", "quality", "performance", "best_practice"]
    patch: Optional[IssuePatch] = None

class ReviewResult(BaseModel):
    summary: str
    issues: List[Issue]


# =========================
# Looser tool schema (easier for the model to fill)
# =========================
class ToolIssue(BaseModel):
    title: str
    description: str
    severity: Literal["critical", "major", "minor"]
    category: Literal["security", "quality", "performance", "best_practice"]
    line: Optional[int] = None
    patch: Optional[Dict[str, str]] = None  # Use proper dict structure for OpenAI compatibility

class EmitIssuesArgs(BaseModel):
    issues: List[ToolIssue] = Field(default_factory=list)

@tool("emit_issues")
def emit_issues_tool(issues: List[ToolIssue]) -> str:
    """Model must call this once with its findings.
    Args: List of ToolIssues
    Return: string
    
    """
    return "ok"


# =========================
# Review Agent (sync, simple)
# =========================
class ReviewAgentSync:
    def __init__(
        self,
        github_token: Optional[str] = None,
        gemini_base_url: str = None,
        gemini_model: str = None,
        gemini_api_key: Optional[str] = None,
        timeout_secs: int = 30,
    ):
        # --- GitHub ---
        self.github_token = github_token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not self.github_token:
            raise RuntimeError("GITHUB_TOKEN (or GH_TOKEN) is required.")

        self.gh_api = "https://api.github.com"

        # --- LLM (Gemini via OpenAI-compatible endpoint) ---
        self.gemini_base_url = gemini_base_url or os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.gemini_model = gemini_model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        if not self.gemini_api_key:
            raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) is required for the model.")

        self.llm = ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            model="gpt-4o-mini",  # Fixed model name (gpt-5-mini doesn't exist)
            temperature=float(os.getenv("REVIEW_TEMP", "0")),
            max_tokens=1200,
        )

        # Use structured output instead of parser
        self.llm_structured = self.llm.with_structured_output(EmitIssuesArgs)
        
        # Remove the parser since we're using structured output
        # self.parser = SimpleJsonOutputParser(pydantic_object=EmitIssuesArgs)

        # Use the structured LLM directly
        self.model_with_tool = self.llm_structured
        # --- Guardrails / tuning ---
        self.timeout_secs = timeout_secs
        self.max_files = int(os.getenv("REVIEW_MAX_FILES", "20"))
        self.only_changed_default = os.getenv("REVIEW_ONLY_CHANGED", "true").lower() == "true"
        self.include_static_default = os.getenv("REVIEW_INCLUDE_STATIC", "true").lower() == "true"
        self.window_context = int(os.getenv("REVIEW_WINDOW_CONTEXT", "12"))  # lines around diffs

        # --- Prompt ---
        self.SYSTEM = (
            "You are a senior code reviewer.\n"
            "Focus on CHANGED_LINES when provided.\n"
            "Return your findings as a JSON object with an 'issues' array.\n"
            "Each finding must have these fields:\n"
            "- severity: critical|major|minor\n"
            "- category: security|quality|performance|best_practice\n"
            "- title: short descriptive title\n"
            "- description: 1-2 line explanation\n"
            "- line: (optional) line number where issue occurs in the provided code snippet\n"
            "- patch: (optional) object with 'before' and 'after' code snippets\n"
            "IMPORTANT: The line numbers you provide should correspond to the line numbers in the code snippet you see.\n"
            "If you see code that starts at line 1, use line 1. If you see code that starts at line 50, use line 50.\n"
            "Example format: issues array with severity, category, title, description, line, and patch fields"
        )
        self.FILE_TMPL = ChatPromptTemplate.from_messages([
            ("system", self.SYSTEM),
            ("human",
             "File: {file}\n"
             "Head SHA: {sha}\n"
             "{changed_hint}\n"
             "Code:\n```\n{code}\n```\n"
             #"Call the tool with your findings. Do not answer in text."
             )
        ])

        # Diff hunk regex
        self.HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    # ------------- GitHub helpers (sync) -------------
    def _gh_headers(self, accept: Optional[str] = None) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if accept:
            h["Accept"] = accept
        return h

    def _gh_get_json(self, url: str, params: Optional[Dict] = None) -> dict:
        r = requests.get(url, headers=self._gh_headers(), params=params, timeout=self.timeout_secs)
        r.raise_for_status()
        return r.json()

    def _gh_get_text(self, url: str, params: Optional[Dict] = None) -> str:
        # Raw content (no base64)
        r = requests.get(url, headers=self._gh_headers("application/vnd.github.raw"), params=params, timeout=self.timeout_secs)
        r.raise_for_status()
        return r.text

    def _paginate(self, url: str, params: Optional[Dict] = None) -> List[dict]:
        items: List[dict] = []
        page = 1
        params = dict(params or {})
        while True:
            params["per_page"] = 100
            params["page"] = page
            r = requests.get(url, headers=self._gh_headers(), params=params, timeout=self.timeout_secs)
            r.raise_for_status()
            chunk = r.json()
            if not chunk:
                break
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return items

    def get_pr(self, owner: str, repo: str, number: int) -> dict:
        return self._gh_get_json(f"{self.gh_api}/repos/{owner}/{repo}/pulls/{number}")

    def list_pr_files_detailed(self, owner: str, repo: str, number: int) -> List[dict]:
        # includes filename, patch, additions/deletions, etc.
        return self._paginate(f"{self.gh_api}/repos/{owner}/{repo}/pulls/{number}/files")

    def get_file_text_at_ref(self, owner: str, repo: str, path: str, ref: str) -> str:
        url = f"{self.gh_api}/repos/{owner}/{repo}/contents/{path}"
        return self._gh_get_text(url, params={"ref": ref})

    # ------------- Diff parsing / windowing -------------
    def changed_lines_from_patch(self, patch: str) -> Set[int]:
        changed: Set[int] = set()
        if not patch:
            return changed
        new_line = None
        for line in patch.splitlines():
            m = self.HUNK_RE.match(line)
            if m:
                start = int(m.group(1))
                _ = int(m.group(2) or "1")
                new_line = start
                continue
            if new_line is None:
                continue
            if line.startswith("+") and not line.startswith("+++"):
                changed.add(new_line)
                new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                # deletion on old side; don't advance new_line
                continue
            else:
                new_line += 1
        return changed

    def clip_to_windows(self, text: str, changed: Set[int], context: int) -> str:
        if not changed:
            return text
        lines = text.splitlines()
        keep: Set[int] = set()
        for ln in changed:
            for i in range(max(1, ln - context), min(len(lines), ln + context) + 1):
                keep.add(i)
        
        # Create line number mapping for context
        chunks: List[str] = []
        cur: List[str] = []
        line_mapping: Dict[int, int] = {}  # new_line -> original_line
        
        for i, line in enumerate(lines, start=1):
            if i in keep:
                cur.append(line)
                line_mapping[len(cur)] = i  # Map new position to original line number
            elif cur:
                chunks.append("\n".join(cur))
                cur = []
                line_mapping.clear()  # Reset for next chunk
        
        if cur:
            chunks.append("\n".join(cur))
        
        return "\n\n# ...\n\n".join(chunks) if chunks else text

    def clip_to_windows_with_line_numbers(self, text: str, changed: Set[int], context: int) -> tuple[str, Dict[int, int]]:
        """
        Clip code to windows around changed lines and return both the clipped code
        and a mapping from clipped line numbers to original line numbers.
        """
        if not changed:
            return text, {}
        
        lines = text.splitlines()
        keep: Set[int] = set()
        for ln in changed:
            for i in range(max(1, ln - context), min(len(lines), ln + context) + 1):
                keep.add(i)
        
        chunks: List[str] = []
        cur: List[str] = []
        line_mapping: Dict[int, int] = {}  # clipped_line -> original_line
        clipped_line_num = 1
        
        for i, line in enumerate(lines, start=1):
            if i in keep:
                cur.append(line)
                line_mapping[clipped_line_num] = i  # Map clipped position to original line number
                clipped_line_num += 1
            elif cur:
                chunks.append("\n".join(cur))
                cur = []
                clipped_line_num = 1  # Reset for next chunk
        
        if cur:
            chunks.append("\n".join(cur))
        
        clipped_code = "\n\n# ...\n\n".join(chunks) if chunks else text
        return clipped_code, line_mapping

    # ------------- Static checks (very light) -------------
    def static_checks_python(self, file: str, code: str, changed: Optional[Set[int]]) -> List[Issue]:
        issues: List[Issue] = []
        lines = code.splitlines()

        def add(line, title, desc, severity="major", category="best_practice", before=None, after=None):
            issues.append(Issue(
                id=f"ST-{file}-{line}-{len(issues)+1}",
                file=file,
                line=line,
                title=title,
                description=desc,
                severity=severity,  # type: ignore
                category=category,  # type: ignore
                patch=(IssuePatch(before=before, after=after) if before is not None and after is not None else None)
            ))

        for ln, text in enumerate(lines, start=1):
            if changed and ln not in changed:
                continue
            t = text.strip()
            if "eval(" in t:
                add(ln, "Avoid eval()", "Use safe parsing/AST or explicit mapping.", "critical", "security")
            if "exec(" in t:
                add(ln, "Avoid exec()", "Refactor to functions or plugins; exec is dangerous.", "critical", "security")
            if "subprocess" in t and "shell=True" in t:
                add(ln, "Subprocess with shell=True", "Avoid shell=True to reduce injection risk.", "major", "security")
            if "requests." in t and "verify=False" in t:
                add(ln, "TLS verification disabled", "Do not disable certificate verification.", "critical", "security")
            if t.startswith("except:"):
                add(ln, "Broad exception handler", "Catch specific exceptions or re-raise.", "minor", "quality")
            if "API_KEY" in t or "SECRET" in t:
                add(ln, "Potential hard-coded secret", "Read from env/secret manager, not source code.", "major", "security")

        return issues

    # ------------- LLM call (one file) -------------
    def _coerce_args(self, args):
        # tool args may be dict OR a JSON string; normalize to dict
        if isinstance(args, str):
            try:
                return json.loads(args or "{}")
            except Exception:
                return {}
        return args or {}
    @sleep_and_retry
    @limits(calls=10, period=60)  # 10 calls per 60 seconds
    def review_one_file(self, file: str, code: str, sha: str, changed: Set[int], only_changed: bool) -> List[Issue]:
        changed_hint = ""
        if only_changed and changed:
            preview = ", ".join(map(str, sorted(changed)[:30]))
            changed_hint = f"CHANGED_LINES: {preview}\nFocus on these lines and their immediate context."

        # Trim to windows for token savings and get line number mapping
        line_mapping = {}
        if only_changed and changed:
            code_for_llm, line_mapping = self.clip_to_windows_with_line_numbers(code, changed, self.window_context)
            print(f"DEBUG: Line mapping: {line_mapping}")
        else:
            code_for_llm = code

        # Use structured output directly - no need for complex parsing
        chain = self.FILE_TMPL | self.model_with_tool
        
        print("-----Debug Statements---")
        print("File:",file)
        print("sha:",sha)
        print("code_for_llm:",code_for_llm)
        print("changed_hint:",changed_hint)
        print("-----Debug Statements---")
        
        # NOTE: synchronous call with structured output
        ai = None
        try:
            ai = chain.invoke({"file": file, "sha": sha, "code": code_for_llm, "changed_hint": changed_hint})
            print("Response from LLM.......",ai)
        except Exception as e:
            print(f"Exception occurred during LLM call: {e}")
            # Return empty list if LLM call fails
            return []
        
        if not ai:
            print("No response from LLM, returning empty list")
            return []
        
        # With structured output, ai should already be EmitIssuesArgs
        parsed = ai
        
        # Handle different response formats from the LLM with better debugging
        issues_to_process = []
        print(f"DEBUG: Response type: {type(parsed)}")
        print(f"DEBUG: Response content: {parsed}")
        
        if isinstance(parsed, list):
            # LLM returned list of ToolIssue directly
            print(f"✅ LLM returned list directly with {len(parsed)} issues")
            if all(isinstance(item, ToolIssue) for item in parsed):
                issues_to_process = parsed
                print(f"✅ All items are ToolIssue objects")
            else:
                print(f"⚠️  Some items are not ToolIssue objects")
                # Try to convert non-ToolIssue items
                for item in parsed:
                    if isinstance(item, ToolIssue):
                        issues_to_process.append(item)
                    else:
                        print(f"⚠️  Skipping non-ToolIssue item: {type(item)} - {item}")
                        
        elif hasattr(parsed, 'issues') and parsed.issues:
            # LLM returned EmitIssuesArgs with issues
            print(f"✅ LLM returned EmitIssuesArgs with {len(parsed.issues)} issues")
            if isinstance(parsed.issues, list):
                issues_to_process = parsed.issues
                print("Here...")
            else:
                print(f"⚠️  parsed.issues is not a list: {type(parsed.issues)}")
                issues_to_process = []
                
        elif hasattr(parsed, 'content') and parsed.content:
            # LLM returned content that might contain issues
            print(f"⚠️  LLM returned content field: {parsed.content}")
            try:
                # Try to parse content as JSON
                content_data = json.loads(parsed.content)
                if isinstance(content_data, dict) and 'issues' in content_data:
                    print(f"✅ Found issues in content: {len(content_data['issues'])}")
                    issues_to_process = content_data['issues']
                else:
                    print(f"⚠️  Content doesn't contain issues field")
                    issues_to_process = []
            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse content as JSON: {e}")
                issues_to_process = []
                
        else:
            print(f"❌ Unexpected response format: {type(parsed)}")
            print(f"❌ Response attributes: {dir(parsed) if hasattr(parsed, '__dict__') else 'No attributes'}")
            return []

        print(f"DEBUG: Final issues_to_process: {len(issues_to_process)} items")
        if issues_to_process:
            print(f"DEBUG: First issue sample: {issues_to_process[0] if issues_to_process else 'None'}")

        # Map ToolIssue -> Issue, add IDs, filter to changed lines if requested
        out: List[Issue] = []
        print(f"DEBUG: Starting conversion of {len(issues_to_process)} issues")
        
        for idx, ti in enumerate(issues_to_process, start=1):
            try:
                print(f"DEBUG: Processing issue {idx}: {getattr(ti, 'title', 'No title')}")
                
                # Validate required fields
                if not hasattr(ti, 'title') or not hasattr(ti, 'description') or not hasattr(ti, 'severity') or not hasattr(ti, 'category'):
                    print(f"⚠️  Issue {idx} missing required fields, skipping")
                    continue
                
                # Check if line should be filtered and convert clipped line numbers to original
                line_num = getattr(ti, 'line', None)
                original_line_num = None
                
                if line_num is not None:
                    # Convert clipped line number to original file line number
                    if line_mapping and line_num in line_mapping:
                        original_line_num = line_mapping[line_num]
                        print(f"✅ Converted clipped line {line_num} to original line {original_line_num}")
                    else:
                        original_line_num = line_num
                        print(f"⚠️  Line {line_num} not in mapping, using as-is")
                else:
                    original_line_num = None
                
                # Check if line should be filtered using original line numbers
                if only_changed and changed and (original_line_num is not None) and (original_line_num not in changed):
                    print(f"⚠️  Issue {idx} on original line {original_line_num} not in changed lines, skipping")
                    continue
                
                # Handle patch parsing - LLM might return dict instead of IssuePatch
                patch_obj = None
                if hasattr(ti, 'patch') and ti.patch:
                    patch = ti.patch
                    if isinstance(patch, dict):
                        # If it's already a dict with before/after keys
                        try:
                            before = patch.get("before", "")
                            after = patch.get("after", "")
                            patch_obj = IssuePatch(before=before, after=after)
                            print(f"✅ Created patch from dict: before='{before[:50]}...', after='{after[:50]}...'")
                        except Exception as e:
                            print(f"❌ Patch dict parsing error: {e}")
                            patch_obj = None
                    elif isinstance(patch, str):
                        # Try to parse string format like "before: ... after: ..."
                        try:
                            if "before:" in patch and "after:" in patch:
                                parts = patch.split("after:")
                                before_part = parts[0].replace("before:", "").strip()
                                after_part = parts[1].strip()
                                patch_obj = IssuePatch(before=before_part, after=after_part)
                                print(f"✅ Created patch from string: before='{before_part[:50]}...', after='{after_part[:50]}...'")
                            else:
                                # If it's just a string, create a simple patch
                                patch_obj = IssuePatch(before="", after=patch)
                                print(f"✅ Created patch from string (no before): after='{patch[:50]}...'")
                        except Exception as e:
                            print(f"❌ Patch string parsing error: {e}")
                            patch_obj = None
                    elif hasattr(patch, 'before') and hasattr(patch, 'after'):
                        # If it's already an IssuePatch object
                        patch_obj = patch
                        print(f"✅ Using existing IssuePatch object")
                    else:
                        print(f"⚠️  Unknown patch format: {type(patch)}")
                
                # Create the Issue object
                issue = Issue(
                    id=f"AI-{file}-{original_line_num or 0}-{idx}",
                    file=file,
                    line=original_line_num,
                    title=getattr(ti, 'title', 'Unknown'),
                    description=getattr(ti, 'description', 'No description'),
                    severity=getattr(ti, 'severity', 'minor'),
                    category=getattr(ti, 'category', 'quality'),
                    patch=patch_obj,
                )
                
                out.append(issue)
                print(f"✅ Successfully created issue {idx}: {issue.title}")
                
            except Exception as e:
                print(f"❌ Error processing issue {idx}: {e}")
                print(f"❌ Issue data: {ti}")
                continue
        
        print(f"DEBUG: Successfully converted {len(out)} out of {len(issues_to_process)} issues")
        print(f"Before returning---->{out}")    
        return out


    # ------------- Summary / dedupe -------------
    def dedupe(self, issues: List[Issue]) -> List[Issue]:
        seen = set()
        uniq: List[Issue] = []
        for i in issues:
            key = (i.file, i.line or 0, i.title.strip().lower())
            if key not in seen:
                seen.add(key)
                uniq.append(i)
        return uniq

    def summarize(self, issues: List[Issue]) -> str:
        if not issues:
            return "No issues found."
        sev_rank = {"critical": 0, "major": 1, "minor": 2}
        counts = {"critical": 0, "major": 0, "minor": 0}
        by_cat = {"security": 0, "quality": 0, "performance": 0, "best_practice": 0}
        for i in issues:
            counts[i.severity] = counts.get(i.severity, 0) + 1
            by_cat[i.category] = by_cat.get(i.category, 0) + 1
        total = len(issues)
        top = sorted(issues, key=lambda x: (sev_rank.get(x.severity, 9), x.line or 1))[:3]
        bullets = "; ".join([f"{i.severity} in {i.file}:{i.line or '-'} — {i.title}" for i in top])
        return (
            f"{total} findings "
            f"(critical {counts['critical']}, major {counts['major']}, minor {counts['minor']}); "
            f"by category: sec {by_cat['security']}, quality {by_cat['quality']}, "
            f"perf {by_cat['performance']}, best {by_cat['best_practice']}. "
            f"Top: {bullets}"
        )

    # ------------- Public entrypoint -------------
    def review_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
        paths: Optional[List[str]] = None,
        only_changed: Optional[bool] = None,
        include_static: Optional[bool] = None,
    ) -> ReviewResult:
        """
        Synchronous, straightforward execution:
          1) Fetch PR head SHA, files, diffs, contents
          2) (Optional) static checks
          3) LLM review per file (tool-calling)
          4) Dedupe + summarize
        """
        only_changed = self.only_changed_default if only_changed is None else only_changed
        include_static = self.include_static_default if include_static is None else include_static

        # --- 1) PR meta + files/diffs ---
        pr = self.get_pr(owner, repo, number)
        head_sha = (pr.get("head") or {}).get("sha") or ""
        if not head_sha:
            return ReviewResult(summary="PR head SHA not found.", issues=[])

        detailed = self.list_pr_files_detailed(owner, repo, number)
        filenames: List[str] = []
        changed_map: Dict[str, Set[int]] = {}
        for item in detailed:
            fn = item.get("filename")
            if not fn:
                continue
            if paths and fn not in paths:
                continue
            filenames.append(fn)
            changed_map[fn] = self.changed_lines_from_patch(item.get("patch") or "")

        if not filenames:
            return ReviewResult(summary="No files to review.", issues=[])

        # Cap files
        filenames = filenames[: self.max_files]

        # --- fetch contents at head sha ---
        contents: Dict[str, str] = {}
        for fn in filenames:
            try:
                contents[fn] = self.get_file_text_at_ref(owner, repo, fn, head_sha)
            except Exception:
                contents[fn] = ""

        # --- 2) Static checks (light, Python only) ---
        all_issues: List[Issue] = []
        if include_static:
            for fn in filenames:
                if fn.lower().endswith(".py") and contents.get(fn):
                    all_issues.extend(self.static_checks_python(fn, contents[fn], changed_map.get(fn)))

        # --- 3) LLM review per file (sequential, simple) ---
        for fn in filenames:
            code = contents.get(fn) or ""
            if not code:
                continue
            issues = self.review_one_file(fn, code, head_sha, changed_map.get(fn, set()), only_changed)
            all_issues.extend(issues)

        # --- 4) Dedupe + summarize ---
        all_issues = self.dedupe(all_issues)
        summary = self.summarize(all_issues)

        return ReviewResult(summary=summary, issues=all_issues)