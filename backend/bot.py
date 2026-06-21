"""Resume generation orchestrator.

`Bot` drives the full pipeline around the module-level pydantic-ai agents in
`llm.agent`: CSV ingest into the vector store, authoritative context building,
generation, stored-language injection, education merge and translation.
File rendering is the API layer's responsibility.
"""

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Optional, Union

from llm import agent
from models.education import Education
from models.language import Language
from models.resume import ResumeOutputFormat
from utils.db_storage import DBStorage
from utils.generation_context import build_generation_context, extract_languages, format_display_date
from utils.ingest import load_csv_documents
from utils.logging_utils import set_user_context


class Bot:
    """Orchestrates resume generation and translation for one user."""

    def __init__(
        self,
        user_id: str,
        vector_store: Any = None,
        model: Union[str, Any, None] = None,
        db: Any = None,
        auto_ingest: bool = True,
        jobs_csv: str = "jobs.csv",
    ):
        """Initialize Bot.

        Args:
            user_id: Owner of the stored experience/skills; required.
            vector_store: PGVectorStore (or compatible) backing the retrieval tool.
            model: pydantic-ai model name or instance; defaults to `agent.DEFAULT_MODEL`.
            db: Optional DB handle passed to the agent tools (defaults to DBStorage).
            auto_ingest: If True, loads jobs_csv into the store (if file exists).
            jobs_csv: Path to CSV to ingest.
        """
        if not user_id:
            raise ValueError("user_id is required to generate a resume")
        self.user_id = user_id
        self.vector_store = vector_store
        self.model = agent.normalize_model_name(model)
        self.db = db
        self.logger = logging.getLogger("betterresume.bot")
        self.logger.info(
            "Bot init model=%s has_store=%s auto_ingest=%s jobs_csv=%s user=%s",
            self.model, bool(vector_store), auto_ingest, jobs_csv, user_id,
        )

        self._auto_ingest_task = None
        if auto_ingest and jobs_csv and os.path.isfile(jobs_csv):
            self._start_auto_ingest(jobs_csv)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def _start_auto_ingest(self, jobs_csv: str):
        """Kick off auto-ingest synchronously or as a background task, depending on loop state."""
        if not self.vector_store:
            self.logger.warning("Auto-ingest skipped: vector store missing")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop; run to completion.
            asyncio.run(self._auto_ingest_jobs(jobs_csv))
            return
        # Running loop; schedule background task.
        self._auto_ingest_task = loop.create_task(self._auto_ingest_jobs(jobs_csv))

    async def _auto_ingest_jobs(self, jobs_csv: str):
        try:
            self.logger.info("Resetting pgvector rows for fresh ingest user=%s", self.user_id)
            try:
                await self.vector_store.adelete_user_documents(self.user_id)
            except Exception:
                pass

            docs = load_csv_documents(jobs_csv)
            ids = [f"{self.user_id}_{i}" for i in range(len(docs))]
            self.logger.info("Auto-ingesting %d rows from %s for user=%s", len(docs), jobs_csv, self.user_id)
            await self.vector_store.aadd_documents(docs, ids, user_id=self.user_id)
        except Exception as e:
            self.logger.warning("Auto-ingest failed for %s: %s", jobs_csv, e)

    # ------------------------------------------------------------------
    # Stored-data helpers
    # ------------------------------------------------------------------

    def _fetch_generation_context(self) -> Optional[str]:
        """Build the authoritative context block (current date, computed years of
        experience, spoken languages) from the user's stored records."""
        try:
            records = DBStorage().get_job_experiences(self.user_id)
            context = build_generation_context(records)
            self.logger.info("Generation context built from %d stored records", len(records))
            return context
        except Exception as e:
            self.logger.warning("Could not build generation context: %s", e)
            return None

    def _fetch_stored_languages(self, storage: DBStorage) -> list:
        records = storage.get_job_experiences(self.user_id, type_filter="language")
        return [
            Language(name=name, proficiency=proficiency)
            for name, proficiency in extract_languages(records)
        ]

    def _inject_stored_languages(self, resume: ResumeOutputFormat) -> None:
        """Fallback: if the model omitted the languages section despite the context
        block, fill it from stored data. When the model did produce languages we keep
        its output — it writes the names and proficiency levels in the resume's
        language, which raw DB values are not guaranteed to be in."""
        if resume.resume_section.languages:
            return
        try:
            stored_languages = self._fetch_stored_languages(DBStorage())
            if stored_languages:
                resume.resume_section.languages = stored_languages
                self.logger.info("Injected %d stored languages (model omitted them)", len(stored_languages))
        except Exception as e:
            self.logger.warning("Could not inject stored languages: %s", e)

    def _fetch_education(self) -> list:
        """Map stored education records (DB schema) onto the resume Education model."""
        records = DBStorage().get_job_experiences(self.user_id, type_filter="education")
        self.logger.info("Fetched %d education records for user=%s", len(records), self.user_id)
        education_list = []
        for rec in records:
            # DB: type, company, description, role, location, start_date, end_date
            # Model: institution, degree, dates
            date_parts = [format_display_date(rec.get("start_date")), format_display_date(rec.get("end_date"))]
            education_list.append(Education(
                institution=rec.get("company") or "",
                degree=(rec.get("description") or "") or (rec.get("role") or ""),
                dates=" - ".join(p for p in date_parts if p),
            ))
        return education_list

    # ------------------------------------------------------------------
    # Generation pipeline
    # ------------------------------------------------------------------

    async def _pipeline(self, jd: str, merge_education: bool) -> AsyncIterator[dict]:
        """Single generation pipeline; both public entry points consume this."""
        if self._auto_ingest_task:
            await self._auto_ingest_task
        set_user_context(self.user_id)

        self.logger.info("Generate resume start; jd_chars=%d", len(jd or ""))
        yield {"stage": "invoking_llm", "message": "Invoking LLM"}
        extra_context = self._fetch_generation_context()
        resume = await agent.generate(
            jd,
            user_id=self.user_id,
            vector_store=self.vector_store,
            db=self.db,
            model=self.model,
            require_tool_call=True,
            extra_context=extra_context,
        )
        self.logger.info("Agent returned resume; language=%s", resume.language)
        self._inject_stored_languages(resume)
        yield {"stage": "parsed", "message": "Initial resume parsed", "data": {"language": resume.language}}

        if (resume.language or "").lower() != "en":
            yield {"stage": "translating", "message": "Translating resume"}
            resume = await self.translate_resume(resume, jd)
            self.logger.info("Translation applied; language=%s", resume.language)
            yield {"stage": "translated", "message": "Translation complete", "data": {"language": resume.language}}

        if merge_education:
            resume.resume_section.education = self._fetch_education()

        yield {"stage": "done", "message": "Resume generation complete", "result": resume}

    async def generate_resume(self, jd: str) -> ResumeOutputFormat:
        resume = None
        async for event in self._pipeline(jd, merge_education=False):
            if event["stage"] == "done":
                resume = event["result"]
        return resume

    async def generate_resume_progress(self, jd: str) -> AsyncIterator[dict]:
        """Async generator yielding progress events; leaves file creation to API layer."""
        async for event in self._pipeline(jd, merge_education=True):
            yield event

    async def translate_resume(self, r: ResumeOutputFormat, original_jd: str) -> ResumeOutputFormat:
        if isinstance(r, dict):
            r = ResumeOutputFormat.model_validate(r)
        return await agent.translate(r, original_jd, user_id=self.user_id, model=self.model)


if __name__ == "__main__":
    import argparse
    import json

    from llm.vector_store import PGVectorStore

    p = argparse.ArgumentParser()
    p.add_argument("--job", required=True)
    p.add_argument("--user", default="cli_user")
    a = p.parse_args()
    jd = open(a.job).read()
    b = Bot(user_id=a.user, vector_store=PGVectorStore())
    out = asyncio.run(b.generate_resume(jd))
    print(json.dumps(out.model_dump(), indent=2, ensure_ascii=False))
