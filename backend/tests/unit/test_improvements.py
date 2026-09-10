"""'Apply improvements': a review's change requests ride along on a
regeneration -- into the generation prompt and into the result cache key."""

from unittest.mock import AsyncMock, MagicMock, patch

from api.schemas import ResumeRequest
from api.utils import _build_result_signature
from bot import Bot
from llm import agent, model_config
from tests.unit.test_resume_cache_signature import _cfg


def test_improvements_block_is_empty_without_requests():
    assert agent.improvements_block(None) == ""
    assert agent.improvements_block([]) == ""
    assert agent.improvements_block(["", "   "]) == ""


def test_improvements_block_lists_each_request_and_forbids_fabrication():
    block = agent.improvements_block(["Add a metric to bullet 2", "Mention Terraform  under\nskills"])
    assert block.startswith("IMPROVEMENT REQUESTS")
    assert "- Add a metric to bullet 2" in block
    assert "- Mention Terraform under skills" in block  # whitespace collapsed
    assert "Never invent" in block


def test_improvements_block_caps_count_and_length():
    block = agent.improvements_block(["x" * 5000] + [f"item {i}" for i in range(50)])
    lines = [l for l in block.split("\n") if l.startswith("- ")]
    assert len(lines) == agent.MAX_IMPROVEMENTS
    assert len(lines[0]) == 2 + agent.MAX_IMPROVEMENT_CHARS


async def test_generate_appends_the_block_to_the_prompt(sample_resume_output):
    captured = {}

    async def _fake_run(agent_obj, prompt, **kwargs):
        captured["prompt"] = prompt
        result = MagicMock()
        result.output = sample_resume_output
        return result

    with patch("llm.agent.get_model_config", return_value=_cfg("openrouter:m")), \
         patch("llm.agent._run_with_fallback", _fake_run):
        await agent.generate("Senior engineer", user_id="u1", extra_context="CONTEXT",
                             improvements=["Quantify the Kafka bullet"])
    assert captured["prompt"].startswith("Senior engineer\n\nCONTEXT")
    assert "IMPROVEMENT REQUESTS" in captured["prompt"]
    assert "- Quantify the Kafka bullet" in captured["prompt"]


async def test_generate_prompt_is_unchanged_without_improvements(sample_resume_output):
    captured = {}

    async def _fake_run(agent_obj, prompt, **kwargs):
        captured["prompt"] = prompt
        result = MagicMock()
        result.output = sample_resume_output
        return result

    with patch("llm.agent.get_model_config", return_value=_cfg("openrouter:m")), \
         patch("llm.agent._run_with_fallback", _fake_run):
        await agent.generate("Senior engineer", user_id="u1", extra_context="CONTEXT")
    assert captured["prompt"] == "Senior engineer\n\nCONTEXT"


async def test_bot_passes_improvements_to_the_agent(sample_resume_output):
    generate = AsyncMock(return_value=sample_resume_output)
    with patch("llm.agent.get_model_config", return_value=_cfg("openrouter:m")), \
         patch("llm.agent.generate", generate), \
         patch("bot.DBStorage", return_value=MagicMock(get_job_experiences=lambda *a, **k: [], get_user_languages=lambda *a, **k: [])):
        bot = Bot(user_id="u1", auto_ingest=False)
        await bot.generate_resume("jd", improvements=["Add metrics"])
    assert generate.call_args.kwargs["improvements"] == ["Add metrics"]


def test_result_signature_changes_with_improvements_only_when_present():
    with patch("llm.agent.get_model_config", return_value=_cfg("openrouter:m")):
        plain = _build_result_signature(ResumeRequest(job_description="jd"), "csv", "job")
        empty = _build_result_signature(ResumeRequest(job_description="jd", improvements=["  "]), "csv", "job")
        improved = _build_result_signature(ResumeRequest(job_description="jd", improvements=["Add metrics"]), "csv", "job")
        improved_again = _build_result_signature(ResumeRequest(job_description="jd", improvements=["Add metrics"]), "csv", "job")
        other = _build_result_signature(ResumeRequest(job_description="jd", improvements=["Add Terraform"]), "csv", "job")
    assert plain == empty, "blank requests must not invalidate the plain cache entry"
    assert improved != plain
    assert improved == improved_again
    assert other != improved
