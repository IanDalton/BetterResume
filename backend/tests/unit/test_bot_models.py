"""Bot resolves generation and translation models independently and records
which model actually served the run."""

from unittest.mock import patch

from bot import Bot
from llm import model_config


def _cfg(gen="openrouter:gen/x", trans="google-gla:gemini-2.5-flash-lite"):
    return model_config.ModelConfig(
        generation=model_config.TaskModels(gen, "openrouter:gen/fb"),
        translation=model_config.TaskModels(trans, None),
        import_=model_config.TaskModels("openrouter:imp/x", None),
    )


def test_models_resolved_per_task_from_config():
    with patch("llm.agent.get_model_config", return_value=_cfg()):
        bot = Bot(user_id="u1", auto_ingest=False)
    assert bot.generation_model == "openrouter:gen/x"
    assert bot.translation_model == "google-gla:gemini-2.5-flash-lite"
    assert bot.model == bot.generation_model


def test_explicit_model_applies_to_both_tasks():
    bot = Bot(user_id="u1", model="google-gla:gemini-2.5-flash-lite", auto_ingest=False)
    assert bot.generation_model == "google-gla:gemini-2.5-flash-lite"
    assert bot.translation_model == "google-gla:gemini-2.5-flash-lite"


async def test_generate_records_model_used(stub_vector_store, sample_resume_output):
    from pydantic_ai.models.test import TestModel

    bot = Bot(
        user_id="u1",
        vector_store=stub_vector_store,
        model=TestModel(custom_output_args=sample_resume_output.model_dump()),
        db=None,
        auto_ingest=False,
    )
    with patch.object(Bot, "_fetch_generation_context", return_value=None):
        await bot.generate_resume("Backend role")

    assert bot.last_generation_model is not None
    assert bot.last_generation_fallback_used is False
    assert bot.last_fallback_used is False


async def test_generate_records_token_usage(stub_vector_store, sample_resume_output):
    """`Bot` must capture usage from `agent.generate` so callers (the eval
    runner) can read it off `last_input_tokens` / `last_output_tokens` --
    before this, usage was logged and discarded."""
    from pydantic_ai.models.test import TestModel

    bot = Bot(
        user_id="u1",
        vector_store=stub_vector_store,
        model=TestModel(custom_output_args=sample_resume_output.model_dump()),
        db=None,
        auto_ingest=False,
    )
    with patch.object(Bot, "_fetch_generation_context", return_value=None):
        await bot.generate_resume("Backend role")

    assert bot.last_input_tokens is not None and bot.last_input_tokens > 0
    assert bot.last_output_tokens is not None and bot.last_output_tokens > 0
