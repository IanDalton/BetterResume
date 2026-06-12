"""Tests for Bot orchestration (translation trigger, education merge, ingest, guards)."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import Bot
from models.language import Language
from models.resume import ResumeOutputFormat


@contextmanager
def fake_agent(generated: ResumeOutputFormat, translated: ResumeOutputFormat = None):
    """Patch the llm.agent module functions with canned-resume AsyncMocks."""
    generate = AsyncMock(return_value=generated)
    translate = AsyncMock(return_value=translated if translated is not None else generated)
    with patch("llm.agent.generate", generate), patch("llm.agent.translate", translate):
        yield generate, translate


def _resume(sample, language):
    r = ResumeOutputFormat.model_validate(sample.model_dump())
    r.language = language
    return r


def test_bot_requires_user_id():
    with pytest.raises(ValueError, match="user_id"):
        Bot(user_id=None, auto_ingest=False)


async def test_generate_resume_english_skips_translation(sample_resume_output):
    bot = Bot(user_id="u1", auto_ingest=False)

    with fake_agent(_resume(sample_resume_output, "en")) as (generate, translate):
        result = await bot.generate_resume("some job description")

    assert result.language == "en"
    generate.assert_awaited_once()
    translate.assert_not_awaited()


async def test_generate_resume_non_english_triggers_translation(sample_resume_output):
    bot = Bot(user_id="u1", auto_ingest=False)

    with fake_agent(
        generated=_resume(sample_resume_output, "es"),
        translated=_resume(sample_resume_output, "es"),
    ) as (generate, translate):
        await bot.generate_resume("descripción del puesto")

    translate.assert_awaited_once()


def _storage_with_records(records):
    """MagicMock DBStorage whose get_job_experiences honors type_filter like the real one."""
    storage = MagicMock()

    def get_job_experiences(user_id, type_filter=None):
        if type_filter is None:
            return records
        return [r for r in records if r.get("type") == type_filter]

    storage.get_job_experiences.side_effect = get_job_experiences
    return storage


async def test_generate_resume_progress_yields_stages_and_merges_education(sample_resume_output):
    bot = Bot(user_id="u1", auto_ingest=False)

    fake_storage = _storage_with_records([
        {"type": "education", "company": "MIT", "description": "M.S. Computer Science", "start_date": "01/01/2021", "end_date": "01/12/2025"},
    ])

    events = []
    with fake_agent(_resume(sample_resume_output, "en")), patch("bot.DBStorage", return_value=fake_storage):
        async for event in bot.generate_resume_progress("job description"):
            events.append(event)

    stages = [e["stage"] for e in events]
    assert stages == ["invoking_llm", "parsed", "done"]

    final = events[-1]["result"]
    assert len(final.resume_section.education) == 1
    assert final.resume_section.education[0].institution == "MIT"
    assert final.resume_section.education[0].degree == "M.S. Computer Science"
    # Stored DD/MM/YYYY must be reformatted for display, not leaked raw
    assert final.resume_section.education[0].dates == "01/2021 - 12/2025"
    fake_storage.get_job_experiences.assert_any_call("u1", type_filter="education")


async def test_generate_resume_progress_injects_stored_languages(sample_resume_output):
    bot = Bot(user_id="u1", auto_ingest=False)

    fake_storage = _storage_with_records([
        {"type": "language", "role": "English", "description": "Full professional proficiency (C2)"},
        {"type": "language", "role": "Spanish", "description": "Native"},
    ])

    events = []
    with fake_agent(_resume(sample_resume_output, "en")), patch("bot.DBStorage", return_value=fake_storage):
        async for event in bot.generate_resume_progress("job description"):
            events.append(event)

    final = events[-1]["result"]
    languages = final.resume_section.languages
    assert [(l.name, l.proficiency) for l in languages] == [
        ("English", "Full professional proficiency (C2)"),
        ("Spanish", "Native"),
    ]


async def test_model_provided_languages_are_kept(sample_resume_output):
    """When the model already produced languages (localized to the resume's language),
    the stored raw DB values must NOT overwrite them."""
    generated = _resume(sample_resume_output, "en")
    generated.resume_section.languages = [
        Language(name="English", proficiency="Full professional proficiency (C2)"),
        Language(name="Spanish", proficiency="Native"),
    ]
    bot = Bot(user_id="u1", auto_ingest=False)

    fake_storage = _storage_with_records([
        {"type": "language", "role": "Ingles", "description": "Full professional proficiency (C2)"},
        {"type": "language", "role": "Español", "description": "Native"},
    ])

    with fake_agent(generated), patch("bot.DBStorage", return_value=fake_storage):
        result = await bot.generate_resume("job description")

    assert [l.name for l in result.resume_section.languages] == ["English", "Spanish"]


async def test_stored_languages_injected_before_translation(sample_resume_output):
    """Languages must be injected pre-translation so the translator localizes them."""
    bot = Bot(user_id="u1", auto_ingest=False)

    fake_storage = _storage_with_records([
        {"type": "language", "role": "English", "description": "Full professional proficiency (C2)"},
    ])

    with fake_agent(
        generated=_resume(sample_resume_output, "es"),
        translated=_resume(sample_resume_output, "es"),
    ) as (generate, translate), patch("bot.DBStorage", return_value=fake_storage):
        await bot.generate_resume("descripción del puesto")

    passed_to_translate = translate.await_args.args[0]
    assert [(l.name, l.proficiency) for l in passed_to_translate.resume_section.languages] == [
        ("English", "Full professional proficiency (C2)"),
    ]


async def test_generate_resume_passes_authoritative_context_to_agent(sample_resume_output):
    bot = Bot(user_id="u1", auto_ingest=False)

    fake_storage = _storage_with_records([
        {"type": "job", "company": "Acme", "start_date": "01/01/2024", "end_date": "present"},
        {"type": "language", "role": "English", "description": "Full professional proficiency (C2)"},
    ])

    with fake_agent(_resume(sample_resume_output, "en")) as (generate, _), \
            patch("bot.DBStorage", return_value=fake_storage):
        await bot.generate_resume("job description")

    extra_context = generate.await_args.kwargs["extra_context"]
    assert "Today's date" in extra_context
    assert "English — Full professional proficiency (C2)" in extra_context
    assert "total professional experience" in extra_context


async def test_generate_resume_survives_context_failure(sample_resume_output):
    """If the DB is unreachable the context is skipped, not fatal."""
    bot = Bot(user_id="u1", auto_ingest=False)

    with fake_agent(_resume(sample_resume_output, "en")) as (generate, _), \
            patch("bot.DBStorage", side_effect=RuntimeError("db down")):
        result = await bot.generate_resume("job description")

    assert result.language == "en"
    assert generate.await_args.kwargs["extra_context"] is None


async def test_generate_resume_progress_translates_non_english(sample_resume_output):
    bot = Bot(user_id="u1", auto_ingest=False)

    fake_storage = MagicMock()
    fake_storage.get_job_experiences.return_value = []

    events = []
    with fake_agent(
        generated=_resume(sample_resume_output, "fr"),
        translated=_resume(sample_resume_output, "fr"),
    ) as (generate, translate), patch("bot.DBStorage", return_value=fake_storage):
        async for event in bot.generate_resume_progress("description de poste"):
            events.append(event)

    stages = [e["stage"] for e in events]
    assert stages == ["invoking_llm", "parsed", "translating", "translated", "done"]
    translate.assert_awaited_once()


async def test_auto_ingest_loads_csv_into_store(tmp_path, stub_vector_store):
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,Acme,Built stuff\njob,Beta,Shipped things\n")

    bot = Bot(
        user_id="u1",
        vector_store=stub_vector_store,
        auto_ingest=True,
        jobs_csv=str(csv_path),
    )
    # Inside a running loop the ingest is a background task — await it
    if bot._auto_ingest_task:
        await bot._auto_ingest_task

    assert stub_vector_store.deleted_users == ["u1"]
    assert len(stub_vector_store.added) == 2
    assert "company: Acme" in stub_vector_store.added[0][1]


async def test_translate_resume_accepts_dict(sample_resume_output):
    bot = Bot(user_id="u1", auto_ingest=False)

    with fake_agent(_resume(sample_resume_output, "en")) as (_, translate):
        result = await bot.translate_resume(sample_resume_output.model_dump(), "jd")

    assert isinstance(result, ResumeOutputFormat)
    # The dict must have been validated into a model before reaching the agent
    passed_resume = translate.await_args.args[0]
    assert isinstance(passed_resume, ResumeOutputFormat)
