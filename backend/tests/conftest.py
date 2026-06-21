import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Auto-load backend/.env so tests work without manual env exports
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

# pydantic-ai's Google provider reads GOOGLE_API_KEY; bridge from GEMINI_API_KEY if needed
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

import pydantic_ai.models

from models.resume import ResumeOutputFormat
from models.resume_section import ResumeSection
from models.job_experience import JobExperience
from models.skill import Skill
from models.education import Education


_STUB_RESUME_CONTEXT = """\
Work Experience:
- Senior Software Engineer at Acme Corp (03/2021 - Present), San Francisco, CA
  Designed microservices architecture handling 10M events/day using Kafka and Kubernetes.
  Led migration to containerized infrastructure, reducing deployment time by 60%.
  Mentored 3 junior engineers through weekly code reviews.

- Software Engineer at Beta Inc (06/2018 - 02/2021), Remote
  Built REST APIs in Python/FastAPI serving 50k req/s with 99.9% uptime.
  Optimized SQL queries on 100M+ row tables, reducing p99 latency from 200ms to 45ms.
  Implemented CI/CD pipelines using GitHub Actions and Docker.

- Junior Developer at Gamma Ltd (07/2016 - 05/2018), Austin, TX
  Developed internal tooling in Python and Django that saved 10 hours/week of manual work.
  Contributed to PostgreSQL schema design for a 5M user product.

Skills: Python, FastAPI, Django, PostgreSQL, Redis, Docker, Kubernetes, Kafka,
SQL, REST APIs, CI/CD, GitHub Actions, distributed systems, microservices, Pandas.

Education: B.S. Computer Science, UC Berkeley (09/2014 - 05/2018)
"""


class StubVectorStore:
    """In-memory PGVectorStore stand-in that returns canned resume context."""

    def __init__(self, user_id: Optional[str] = None):
        self.user_id = user_id
        self.table_name = "test_collection"
        self.added: List[Tuple[str, str]] = []
        self.deleted_users: List[str] = []
        self.queries: List[str] = []

    async def aquery(self, query: str, user_id: Optional[str], n_results: int = 10) -> List[Tuple[str, float]]:
        self.queries.append(query)
        return [(_STUB_RESUME_CONTEXT, 0.1)]

    async def aadd_documents(self, documents: List[str], ids: List[str], user_id: str) -> str:
        self.added.extend(zip(ids, documents))
        return "Documents added successfully."

    async def adelete_user_documents(self, user_id: str) -> str:
        self.deleted_users.append(user_id)
        return "Deleted"

    async def acount_user_documents(self, user_id: str) -> int:
        return len(self.added)


def pytest_addoption(parser):
    parser.addoption(
        "--real-ai",
        action="store_true",
        default=False,
        help="Run tests that make real AI API calls (requires API keys)",
    )
    parser.addoption(
        "--models",
        default="google-gla:gemini-2.5-flash-lite",
        help="Comma-separated model strings for multi-model tests",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "real_ai: requires live API keys")
    config.addinivalue_line("markers", "slow: multi-model comparison, takes several minutes")
    if not config.getoption("--real-ai"):
        # Hard guarantee: no unit test can silently hit a real LLM API
        pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--real-ai"):
        skip = pytest.mark.skip(reason="Pass --real-ai to run tests that call AI APIs")
        for item in items:
            if "real_ai" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def models_under_test(pytestconfig):
    raw = pytestconfig.getoption("--models")
    return [m.strip() for m in raw.split(",") if m.strip()]


@pytest.fixture
def sample_resume_output() -> ResumeOutputFormat:
    return ResumeOutputFormat(
        language="en",
        resume_section=ResumeSection(
            title="Senior Software Engineer",
            professional_summary=(
                "Experienced software engineer with 8+ years building distributed systems "
                "using Python, Kubernetes, and Kafka. Led teams of 5+ engineers and reduced "
                "p99 latency by 40% across core services."
            ),
            experience=[
                JobExperience(
                    position="Senior Software Engineer",
                    company="Acme Corp",
                    location="San Francisco, CA",
                    start_date="03/2021",
                    end_date="Present",
                    description=(
                        "- Designed microservices architecture handling 10M events/day using Kafka\n"
                        "- Led migration to Kubernetes, reducing deployment time by 60%\n"
                        "- Mentored 3 junior engineers through weekly code reviews"
                    ),
                ),
                JobExperience(
                    position="Software Engineer",
                    company="Beta Inc",
                    location="Remote",
                    start_date="06/2018",
                    end_date="02/2021",
                    description=(
                        "- Built REST APIs in Python/FastAPI serving 50k req/s with 99.9% uptime\n"
                        "- Optimized SQL queries, reducing p99 latency from 200ms to 45ms\n"
                        "- Implemented CI/CD pipelines using GitHub Actions and Docker"
                    ),
                ),
            ],
            skills=[
                Skill(
                    name="Python / FastAPI",
                    description="Built high-throughput APIs serving 50k req/s in production",
                ),
                Skill(
                    name="Distributed Systems",
                    description="Kafka and Kubernetes across 5 production microservices",
                ),
            ],
            education=[
                Education(
                    institution="UC Berkeley",
                    degree="B.S. Computer Science",
                    dates="09/2014 - 05/2018",
                )
            ],
        ),
    )


@pytest.fixture
def stub_vector_store() -> StubVectorStore:
    return StubVectorStore(user_id="test_user_001")
