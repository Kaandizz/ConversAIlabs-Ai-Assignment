import argparse
import sys
import time
from pathlib import Path

from config import MAX_CODE_TOKENS, OUTPUT_DIR
from utils.logger import logger


def run_pipeline(repo_path: str, product_request: str) -> int:
    from agent.explorer import RepositoryExplorer
    from agent.metadata_collector import MetadataCollector
    from agent.selector import FileSelector
    from agent.context_builder import ContextBuilder
    from agent.planner import Planner
    from agent.coder import CodeGenerator
    from agent.validator import Validator
    from agent.patcher import Patcher
    from agent.summarizer import Summarizer
    from utils.llm_client import LLMClient
    from utils.filesystem import write_file_safe

    start_time = time.time()
    logger.info("=" * 70)
    logger.info("AI Coding Agent - Starting Execution Pipeline")
    logger.info("=" * 70)
    logger.info(f"Repository: {repo_path}")
    logger.info(f"Request: {product_request[:100]}{'...' if len(product_request) > 100 else ''}")

    try:
        llm_client = LLMClient()
    except Exception as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        return 1

    logger.info("\n" + "-" * 50)
    logger.info("STEP 1: Explore Repository")
    logger.info("-" * 50)
    try:
        explorer = RepositoryExplorer(repo_path)
        repo_data = explorer.explore()
        logger.info("Repository exploration complete")
    except Exception as e:
        logger.error(f"Repository exploration failed: {e}")
        return 2

    logger.info("\n" + "-" * 50)
    logger.info("STEP 2: Collect Project Metadata")
    logger.info("-" * 50)
    try:
        collector = MetadataCollector(repo_path, repo_data["files"])
        project_metadata = collector.collect()
        logger.info("Metadata collection complete")
    except Exception as e:
        logger.error(f"Metadata collection failed: {e}")
        return 3

    logger.info("\n" + "-" * 50)
    logger.info("STEP 3: Identify Relevant Files")
    logger.info("-" * 50)
    try:
        selector = FileSelector(llm_client)
        selected_files = selector.select(
            product_request=product_request,
            project_metadata=project_metadata,
            repo_exploration=repo_data,
        )
        logger.info(f"Selected files: {', '.join(selected_files)}")
    except Exception as e:
        logger.error(f"File selection failed: {e}")
        return 4

    logger.info("\n" + "-" * 50)
    logger.info("STEP 4: Build Planner Context & Generate Plan")
    logger.info("-" * 50)
    try:
        context_builder = ContextBuilder(repo_path)
        planner_context = context_builder.build_planner_context(
            product_request=product_request,
            repo_exploration=repo_data,
            project_metadata=project_metadata,
            selected_files=selected_files,
        )
        planner = Planner(llm_client)
        implementation_plan = planner.plan(planner_context)
        logger.info("Implementation plan generated successfully")
    except Exception as e:
        logger.error(f"Planning failed: {e}")
        return 5

    logger.info("\n" + "-" * 50)
    logger.info("STEP 5: Build Coder Context & Generate Code")
    logger.info("-" * 50)
    try:
        coder_context = context_builder.build_coder_context(
            product_request=product_request,
            implementation_plan=implementation_plan,
            project_metadata=project_metadata,
            selected_files=selected_files,
        )
        coder = CodeGenerator(llm_client)
        min_files = max(1, len(selected_files) - 1)
        logger.info(
            f"Calling Coder LLM: min_expected={min_files} files, "
            f"MAX_CODE_TOKENS={MAX_CODE_TOKENS} (output cap)"
        )
        code_updates = coder.generate(coder_context, min_expected=min_files)
        logger.info(f"Generated {len(code_updates)} file updates")
    except Exception as e:
        logger.error(f"Code generation failed: {e}")
        return 6

    logger.info("\n" + "-" * 50)
    logger.info("STEP 6: Validate Generated Output")
    logger.info("-" * 50)
    try:
        validator = Validator(repo_path)
        validator.validate_repo_state()
        all_ok, validated_updates = validator.validate_updates(code_updates)
        if not all_ok:
            logger.warning("Some updates failed validation but proceeding with valid ones")
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return 7

    logger.info("\n" + "-" * 50)
    logger.info("STEP 7: Apply Patches to Repository")
    logger.info("-" * 50)
    try:
        patcher = Patcher(repo_path, backup=True)
        applied_patches = patcher.apply(validated_updates)
        if not applied_patches:
            logger.error("No patches applied successfully")
            return 8
        logger.info(f"Successfully applied {len(applied_patches)} patches")
    except Exception as e:
        logger.error(f"Patch application failed: {e}")
        return 9

    logger.info("\n" + "-" * 50)
    logger.info("STEP 8: Generate Change Summary")
    logger.info("-" * 50)
    try:
        summary_context = context_builder.build_summary_context(
            product_request=product_request,
            implementation_plan=implementation_plan,
            applied_patches=applied_patches,
        )
        summarizer = Summarizer(llm_client)
        summary = summarizer.summarize(summary_context)
        logger.info("Change summary generated")
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        summary = "*Summary generation failed*"

    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"Total time: {elapsed:.1f}s")
    logger.info(f"Patches applied: {len(applied_patches)}")
    logger.info(f"Outputs in: {OUTPUT_DIR}")
    logger.info("=" * 70)

    print("\n" + "=" * 70)
    print("IMPLEMENTATION PLAN")
    print("=" * 70)
    print(implementation_plan)
    print("\n" + "=" * 70)
    print("CHANGE SUMMARY")
    print("=" * 70)
    print(summary)
    print()

    return 0


def interactive_mode(repo_path: str) -> int:
    print("AI Coding Agent - Interactive Mode")
    print(f"Repository: {repo_path}")
    print("Enter your feature request (Ctrl+C to quit):")
    try:
        product_request = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")
        return 0

    if not product_request:
        print("Empty request.")
        return 1

    return run_pipeline(repo_path, product_request)


def main():
    parser = argparse.ArgumentParser(
        description="AI Coding Agent - Automatically implement feature requests in a repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --repo ../my-node-app --request "Add tags to notes"
  python main.py --repo ../my-node-app --interactive
        """,
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Path to the target repository",
    )
    parser.add_argument(
        "--request",
        type=str,
        default=None,
        help="Feature request in natural language",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enter interactive mode to type request",
    )

    args = parser.parse_args()

    repo = Path(args.repo).resolve()

    if args.interactive:
        sys.exit(interactive_mode(str(repo)))

    if not args.request:
        parser.error("--request is required unless --interactive is used")

    sys.exit(run_pipeline(str(repo), args.request))


if __name__ == "__main__":
    main()
