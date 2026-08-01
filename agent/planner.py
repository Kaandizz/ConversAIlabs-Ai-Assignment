from pathlib import Path
from typing import Any, Dict

from config import MAX_PLAN_TOKENS, OUTPUT_DIR, PROMPTS_DIR
from utils.filesystem import read_file_safe, write_file_safe
from utils.logger import logger


class Planner:
    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.prompt_template = self._load_template()
        self.logger = logger

    def _load_template(self) -> str:
        template_path = PROMPTS_DIR / "planner.md"
        content = read_file_safe(template_path)
        if content is None:
            raise RuntimeError(f"Could not load planner prompt template: {template_path}")
        return content

    def _render_template(self, context: Dict[str, str]) -> str:
        result = self.prompt_template
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, value)
        return result

    def plan(self, context: Dict[str, str]) -> str:
        self.logger.info("Generating implementation plan...")

        rendered_prompt = self._render_template(context)

        try:
            response = self.llm_client.chat(
                system_prompt=(
                    "You are a careful Senior Software Engineer creating implementation plans. "
                    "Follow the output format exactly. Be brief and specific."
                ),
                user_prompt=rendered_prompt,
                temperature=0.0,
                max_tokens=MAX_PLAN_TOKENS,
            )

            plan_md = response.strip()
            if not plan_md:
                raise RuntimeError("Planner returned empty response")

            plan_path = OUTPUT_DIR / "execution_plan.md"
            if write_file_safe(plan_path, plan_md):
                self.logger.info(f"Implementation plan saved to {plan_path}")

            return plan_md

        except Exception as e:
            self.logger.error(f"Planner failed: {e}")
            raise
