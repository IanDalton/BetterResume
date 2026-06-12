import asyncio
import json
import logging
import os
from typing import Optional

from llm.agent import ResumeAgent
from llm.vector_store import PGVectorStore
from models.education import Education
from models.language import Language
from models.resume import ResumeOutputFormat
from utils.db_storage import DBStorage
from utils.generation_context import build_generation_context, extract_languages, format_display_date
from utils.ingest import load_csv_documents
from utils.logging_utils import set_user_context


class Bot:
    """Orchestrates resume generation and translation with a pydantic-ai agent.

    Attributes:
        agent (ResumeAgent): pydantic-ai backed agent (generation + translation).
        vector_store (PGVectorStore): per-user semantic store backing the agent's retrieval tool.
        json_body (dict): The JSON representation of the generated resume.
        writer (BaseWriter): An instance of a writer class for outputting resumes.
    """

    def __init__(
        self,
        writer,
        agent: ResumeAgent,
        vector_store: Optional[PGVectorStore] = None,
        user_id: Optional[str] = None,
        auto_ingest: bool = True,
        jobs_csv: str = "jobs.csv",
    ):
        """Initialize Bot.

        Args:
            writer: Concrete resume writer.
            agent: ResumeAgent implementation.
            vector_store: Optional existing PGVectorStore instance (reuse across calls, e.g., API).
            auto_ingest: If True, loads jobs_csv into the store (if file exists).
            jobs_csv: Path to CSV to ingest.
        """
        self.agent = agent
        self.vector_store = vector_store or agent.vector_store
        if self.vector_store is not None and agent.vector_store is None:
            agent.vector_store = self.vector_store

        self.user_id = user_id
        self.logger = logging.getLogger("betterresume.bot")
        self.logger.info(
            "Bot init model=%s has_store=%s auto_ingest=%s jobs_csv=%s user=%s",
            getattr(agent, "model", None), bool(self.vector_store), auto_ingest, jobs_csv, user_id,
        )

        self._auto_ingest_task = None
        if auto_ingest and jobs_csv and os.path.isfile(jobs_csv):
            self._start_auto_ingest(jobs_csv)

        self.json_body = None
        self.writer = writer

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
            self._auto_ingest_task = None
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

    async def generate_resume(self, jd: str, output_basename: str = "resume") -> ResumeOutputFormat:
        if self._auto_ingest_task:
            await self._auto_ingest_task
        if self.user_id:
            set_user_context(self.user_id)
        else:
            raise ValueError("user_id is required to generate a resume")
        self.logger.info("Generate resume start; jd_chars=%d", len(jd or ""))
        extra_context = self._fetch_generation_context()
        resume = await self.agent.generate(
            jd, user_id=self.user_id, require_tool_call=True, extra_context=extra_context
        )
        self.logger.info("Agent returned resume; language=%s", resume.language)
        self._inject_stored_languages(resume)

        if resume.language.lower() != "en":
            resume = await self.translate_resume(resume, jd)
            self.logger.info("Translation applied; language=%s", resume.language)

        self.json_body = resume.model_dump()
        return resume

    async def generate_resume_progress(self, jd: str):
        """Async generator yielding progress events; leaves file creation to API layer."""
        # Ensure any background ingest completes
        if self._auto_ingest_task:
            try:
                await self._auto_ingest_task
            except Exception:
                pass
        if self.user_id:
            set_user_context(self.user_id)
        else:
            raise ValueError("user_id is required to generate a resume")

        self.logger.info("Streaming: invoking LLM")
        yield {"stage": "invoking_llm", "message": "Invoking LLM"}
        extra_context = self._fetch_generation_context()
        resume = await self.agent.generate(
            jd, user_id=self.user_id, require_tool_call=True, extra_context=extra_context
        )
        self.logger.info("Streaming: LLM complete; language=%s", resume.language)
        self._inject_stored_languages(resume)
        yield {"stage": "parsed", "message": "Initial resume parsed", "data": {"language": getattr(resume, "language", None)}}

        if (getattr(resume, "language", "") or "").lower() != "en":
            self.logger.info("Streaming: translating non-EN -> EN")
            yield {"stage": "translating", "message": "Translating resume"}
            resume = await self.translate_resume(resume, jd)
            yield {"stage": "translated", "message": "Translation complete", "data": {"language": getattr(resume, "language", None)}}

        # Fetch education from DB
        storage = DBStorage()
        education_records = storage.get_job_experiences(self.user_id, type_filter="education")
        self.logger.info("Fetched %d education records for user=%s", len(education_records), self.user_id)
        education_list = []
        for rec in education_records:
            # Map DB record to Education model
            # DB: type, company, description, role, location, start_date, end_date
            # Model: institution, degree, dates
            date_parts = [format_display_date(rec.get("start_date")), format_display_date(rec.get("end_date"))]
            edu = Education(
                institution=rec.get("company") or "",
                degree=(rec.get("description") or "") or (rec.get("role") or ""),
                dates=" - ".join(p for p in date_parts if p),
            )
            education_list.append(edu)

        resume.resume_section.education = education_list
        self.json_body = resume.model_dump()
        self.logger.info("Streaming: done")
        yield {"stage": "done", "message": "Resume generation complete", "result": resume}

    async def translate_resume(self, r: ResumeOutputFormat, original_jd: str) -> ResumeOutputFormat:
        if isinstance(r, dict):
            r = ResumeOutputFormat.model_validate(r)
        return await self.agent.translate(r, original_jd, user_id=self.user_id)


if __name__ == "__main__":
    import argparse

    from resume import WordResumeWriter

    p = argparse.ArgumentParser()
    p.add_argument("--job", required=True)
    p.add_argument("--user", default="cli_user")
    a = p.parse_args()
    jd = open(a.job).read()
    store = PGVectorStore()
    b = Bot(writer=WordResumeWriter(), agent=ResumeAgent(vector_store=store), vector_store=store, user_id=a.user)
    out = asyncio.run(b.generate_resume(jd))
    print(json.dumps(out.model_dump(), indent=2, ensure_ascii=False))
