from typing import Any, Dict

from config import MAX_SUMMARY_TOKENS, OUTPUT_DIR, PROMPTS_DIR
from utils.filesystem import read_file_safe, write_file_safe
from utils.logger import logger


class Summarizer:
    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.prompt_template = self._load_template()
        self.logger = logger

    def _load_template(self) -> str:
        template_path = PROMPTS_DIR / "summary.md"
        content = read_file_safe(template_path)
        if content is None:
            raise RuntimeError(f"Could not load summary prompt template: {template_path}")
        return content

    def _render_template(self, context: Dict[str, str]) -> str:
        result = self.prompt_template
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, value)
        return result

    def summarize(self, context: Dict[str, str]) -> str:
        self.logger.info("Generating change summary...")

        rendered_prompt = self._render_template(context)

        try:
            response = self.llm_client.chat(
                system_prompt=(
                    "You are a Technical Writer summarizing code changes. "
                    "Follow the output Markdown format exactly. Be accurate and brief."
                ),
                user_prompt=rendered_prompt,
                temperature=0.0,
                max_tokens=MAX_SUMMARY_TOKENS,
            )

            summary_md = response.strip()
            if not summary_md:
                raise RuntimeError("Summarizer returned empty response")

            summary_path = OUTPUT_DIR / "summary.md"
            if write_file_safe(summary_path, summary_md):
                self.logger.info(f"Change summary saved to {summary_path}")

            return summary_md

        except Exception as e:
            self.logger.error(f"Summarizer failed: {e}")
            raise
