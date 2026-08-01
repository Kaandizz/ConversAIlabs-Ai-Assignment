from pathlib import Path
from typing import Any, Dict, List, Optional

from config import MAX_CODE_TOKENS, PROMPTS_DIR
from utils.filesystem import read_file_safe
from utils.helpers import parse_file_updates
from utils.logger import logger


class CodeGenerator:
    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.prompt_template = self._load_template()
        self.logger = logger

    def _load_template(self) -> str:
        template_path = PROMPTS_DIR / "coder.md"
        content = read_file_safe(template_path)
        if content is None:
            raise RuntimeError(f"Could not load coder prompt template: {template_path}")
        return content

    def _render_template(self, context: Dict[str, str]) -> str:
        result = self.prompt_template
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, value)
        return result

    def generate(
        self,
        context: Dict[str, str],
        min_expected: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        self.logger.info("Generating code updates...")

        rendered_prompt = self._render_template(context)

        cap = max_tokens if max_tokens is not None else MAX_CODE_TOKENS

        max_attempts = 2
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    retry_prompt = (
                        rendered_prompt
                        + "\n\n## RETRY INSTRUCTIONS\n"
                        + "Your previous response was incomplete or not parseable. "
                        + "You MUST output ALL modified files. "
                    )
                    if min_expected and min_expected > 1:
                        retry_prompt += (
                            f"The plan covers at least {min_expected} files — "
                            f"output EXACTLY {min_expected} FILE blocks. "
                        )
                    retry_prompt += (
                        "Use EXACTLY this format for each file:\n"
                        + "---\n"
                        + "FILE: path/to/file.ext\n"
                        + "ACTION: Replace Entire File\n"
                        + "CONTENT:\n"
                        + "```language\n// code here\n```\n"
                        + "---\n"
                        + "Respond with file updates only. No extra text."
                    )
                    prompt_used = retry_prompt
                    temp = 0.0
                else:
                    prompt_used = rendered_prompt
                    temp = 0.1

                response = self.llm_client.chat(
                    system_prompt=(
                        "You are a careful Senior Software Engineer. "
                        + "Generate complete updated file contents using the EXACT format specified. "
                        + "Wrap each file in code fences. Preserve existing functionality. "
                        + "Do NOT add comments to the code. Be concise."
                    ),
                    user_prompt=prompt_used,
                    temperature=temp,
                    max_tokens=cap,
                )

                if not response.strip():
                    raise RuntimeError("Code generator returned empty response")

                updates = parse_file_updates(response)

                few_files = (
                    min_expected is not None
                    and len(updates) > 0
                    and len(updates) < min_expected
                )
                if few_files and attempt < max_attempts - 1:
                    self.logger.warning(
                        f"Got {len(updates)} file updates, expected at least "
                        f"{min_expected}. Will retry with reminder..."
                    )
                    last_error = RuntimeError(
                        f"Only {len(updates)}/{min_expected} files produced"
                    )
                    continue

                if updates:
                    self.logger.info(
                        f"Generated {len(updates)} file updates (attempt {attempt + 1})"
                    )
                    for u in updates:
                        self.logger.debug(
                            f"  - {u['file_path']}: {len(u['content'])} chars"
                        )
                    return updates
                else:
                    last_error = RuntimeError(
                        f"Could not parse any file updates from response (attempt {attempt + 1})"
                    )
                    self.logger.warning(str(last_error))

            except Exception as e:
                last_error = e
                self.logger.warning(
                    f"Code generation failed (attempt {attempt + 1}): {e}"
                )

        raise RuntimeError(
            f"Code generation failed after {max_attempts} attempts: {last_error}"
        )
