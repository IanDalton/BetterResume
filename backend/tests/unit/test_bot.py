"""Tests for Bot orchestration (translation trigger, education merge, ingest, guards)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import Bot
from models.resume import ResumeOutputFormat


class FakeAgent:
    """Stands in for ResumeAgent: returns canned resumes and records calls."""

    def __init__(self, generated: ResumeOutputFormat, translated: ResumeOutputFormat = None):
        self.model = "fake:model"
        self.vector_store = None
        self._generated = generated
        self._translated = translated or generated
        self.generate = AsyncMock(side_effect=self._generate)
        self.translate = AsyncMock(side_effect=self._translate)

    async def _generate(self, jd, user_id, require_tool_call=True):
        return self._generated

    async def _translate(self, resume, jd, user_id):
        return self._translated


def _resume(sample, language):
    r = ResumeOutputFormat.model_validate(sample.model_dump())
    r.language = language
    return r


async def test_generate_resume_requires_user_id(sample_resume_output):
    bot = Bot(writer=MagicMock(), agent=FakeAgent(sample_resume_output), user_id=None, auto_ingest=False)
    with pytest.raises(ValueError, match="user_id"):
        await bot.generate_resume("jd")


async def test_generate_resume_english_skips_translation(sample_resume_output):
    agent = FakeAgent(_resume(sample_resume_output, "en"))
    bot = Bot(writer=MagicMock(), agent=agent, user_id="u1", auto_ingest=False)

    result = await bot.generate_resume("some job description")

    assert result.language == "en"
    agent.generate.assert_awaited_once()
    agent.translate.assert_not_awaited()
    assert bot.json_body["language"] == "en"


async def test_generate_resume_non_english_triggers_translation(sample_resume_output):
    agent = FakeAgent(
        generated=_resume(sample_resume_output, "es"),
        translated=_resume(sample_resume_output, "es"),
    )
    bot = Bot(writer=MagicMock(), agent=agent, user_id="u1", auto_ingest=False)

    await bot.generate_resume("descripción del puesto")

    agent.translate.assert_awaited_once()


async def test_generate_resume_progress_yields_stages_and_merges_education(sample_resume_output):
    agent = FakeAgent(_resume(sample_resume_output, "en"))
    bot = Bot(writer=MagicMock(), agent=agent, user_id="u1", auto_ingest=False)

    fake_storage = MagicMock()
    fake_storage.get_job_experiences.return_value = [
        {"company": "MIT", "description": "M.S. Computer Science", "start_date": "2019", "end_date": "2021"},
    ]

    events = []
    with patch("bot.DBStorage", return_value=fake_storage):
        async for event in bot.generate_resume_progress("job description"):
            events.append(event)

    stages = [e["stage"] for e in events]
    assert stages == ["invoking_llm", "parsed", "done"]

    final = events[-1]["result"]
    assert len(final.resume_section.education) == 1
    assert final.resume_section.education[0].institution == "MIT"
    assert final.resume_section.education[0].degree == "M.S. Computer Science"
    fake_storage.get_job_experiences.assert_called_once_with("u1", type_filter="education")


async def test_generate_resume_progress_translates_non_english(sample_resume_output):
    agent = FakeAgent(
        generated=_resume(sample_resume_output, "fr"),
        translated=_resume(sample_resume_output, "fr"),
    )
    bot = Bot(writer=MagicMock(), agent=agent, user_id="u1", auto_ingest=False)

    fake_storage = MagicMock()
    fake_storage.get_job_experiences.return_value = []

    events = []
    with patch("bot.DBStorage", return_value=fake_storage):
        async for event in bot.generate_resume_progress("description de poste"):
            events.append(event)

    stages = [e["stage"] for e in events]
    assert stages == ["invoking_llm", "parsed", "translating", "translated", "done"]
    agent.translate.assert_awaited_once()


async def test_auto_ingest_loads_csv_into_store(tmp_path, sample_resume_output, stub_vector_store):
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,Acme,Built stuff\njob,Beta,Shipped things\n")

    agent = FakeAgent(_resume(sample_resume_output, "en"))
    bot = Bot(
        writer=MagicMock(),
        agent=agent,
        vector_store=stub_vector_store,
        user_id="u1",
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
    agent = FakeAgent(_resume(sample_resume_output, "en"))
    bot = Bot(writer=MagicMock(), agent=agent, user_id="u1", auto_ingest=False)

    result = await bot.translate_resume(sample_resume_output.model_dump(), "jd")

    assert isinstance(result, ResumeOutputFormat)
    # The dict must have been validated into a model before reaching the agent
    passed_resume = agent.translate.await_args.args[0]
    assert isinstance(passed_resume, ResumeOutputFormat)
