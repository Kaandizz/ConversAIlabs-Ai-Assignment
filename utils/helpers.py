import re
import json
from typing import Any, Dict, List, Optional, Tuple


def extract_code_blocks(text: str, language: Optional[str] = None) -> List[str]:
    if language:
        pattern = rf"```{re.escape(language)}\s*\n(.*?)```"
    else:
        pattern = r"```(?:\w+)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return [m.strip() for m in matches]


def extract_json(text: str) -> Optional[Any]:
    code_blocks = extract_code_blocks(text, "json")
    for block in code_blocks:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


def extract_section(text: str, section_name: str) -> Optional[str]:
    pattern = rf"(?:^|\n)#{1,6}\s*{re.escape(section_name)}\s*\n(.*?)(?=\n#{1,6}\s|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _strip_code_fences(content: str) -> str:
    content = content.strip()
    pattern = r"^```(?:\w+)?\s*\n(.*?)\n```$"
    match = re.match(pattern, content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content


_BAD_PATH_MARKERS = ("ACTION:", "CONTENT:", "```", "ACTION ", "CONTENT ")


def _clean_file_path(raw: str) -> str:
    raw = raw.strip().strip("`").strip('"').strip("'").strip()
    lines = raw.splitlines()
    if lines:
        raw = lines[0].strip()
    match = re.search(r"([\w.\-\\/]+\.[a-zA-Z0-9]+)\s*$", raw)
    if match:
        candidate = match.group(1)
    else:
        candidate = raw
    for marker in _BAD_PATH_MARKERS:
        if marker in candidate.upper():
            return ""
    return candidate


_HEAD_LABEL_RE = re.compile(
    r"(FILE|PATH|ACTION)\s*:\s*(.+?)(?=\s*(?:FILE|PATH|ACTION|CONTENT)\s*:|\s*```|\n|$)",
    re.IGNORECASE,
)


def _parse_block(block: str) -> Optional[Dict[str, str]]:
    block = block.strip()
    if not block:
        return None

    fence_start = block.find("```")
    head = block[:fence_start] if fence_start != -1 else block

    if not re.search(r"(?:FILE|PATH)\s*:", head, re.IGNORECASE):
        return None

    fields: Dict[str, str] = {}
    for m in _HEAD_LABEL_RE.finditer(head):
        label = m.group(1).upper()
        value = m.group(2).strip()
        if label in ("FILE", "PATH") and "file_path" not in fields:
            fields["file_path"] = value
        elif label == "ACTION":
            fields["action"] = value

    fp = _clean_file_path(fields.get("file_path", ""))
    action = fields.get("action", "Replace Entire File").strip()

    code_blocks = extract_code_blocks(block)
    content = code_blocks[0] if code_blocks else ""

    if not fp or not content:
        return None

    return {
        "file_path": fp,
        "action": action or "Replace Entire File",
        "content": content,
    }


def _find_file_label_positions(text: str) -> List[int]:
    positions: List[int] = []
    for m in re.finditer(r"\b(?:FILE|PATH)\s*:", text, re.IGNORECASE):
        positions.append(m.start())
    return positions


def parse_file_updates(text: str) -> List[Dict[str, str]]:
    updates: List[Dict[str, str]] = []

    text = text.replace("\r\n", "\n")

    positions = _find_file_label_positions(text)
    if positions:
        for i, start in enumerate(positions):
            end = positions[i + 1] if i + 1 < len(positions) else len(text)
            block = text[start:end]
            parsed = _parse_block(block)
            if parsed:
                updates.append(parsed)

    if not updates:
        code_blocks = extract_code_blocks(text)
        for block in code_blocks:
            first_line_match = re.match(
                r"//\s*(.+?\.(?:js|jsx|ts|tsx|py|go|rs|java|cs|rb|php))",
                block,
            )
            if first_line_match:
                file_path = first_line_match.group(1).strip()
                content = block[first_line_match.end() :].strip()
                if file_path and content:
                    updates.append({
                        "file_path": file_path,
                        "action": "Replace Entire File",
                        "content": content,
                    })

    seen = set()
    unique_updates: List[Dict[str, str]] = []
    for u in updates:
        key = u["file_path"]
        if key not in seen:
            seen.add(key)
            unique_updates.append(u)

    return unique_updates


def count_tokens_approx(text: str) -> int:
    words = len(re.findall(r"\w+", text))
    chars = len(text)
    return max(words, chars // 4)


def truncate_text(text: str, max_tokens: int) -> str:
    current_tokens = count_tokens_approx(text)
    if current_tokens <= max_tokens:
        return text

    ratio = max_tokens / current_tokens
    target_chars = int(len(text) * ratio * 0.9)
    return text[:target_chars] + "\n\n[...truncated...]"


def clean_markdown(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()
