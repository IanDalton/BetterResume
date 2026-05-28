import os
import sys
from pathlib import Path
from typing import Any, Optional

import pytest
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Auto-load backend/.env so tests work without manual env exports
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

# langchain-google-genai reads GOOGLE_API_KEY; bridge from GEMINI_API_KEY if needed
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from langchain.tools import BaseTool
from pydantic import Field

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


class _StubPGVectorTool(BaseTool):
    """Minimal BaseTool stub that returns canned resume context without touching Postgres."""

    name: str = "PGVectorTool"
    description: str = "Retrieve relevant experience from the user's background."
    user_id: Optional[str] = Field(default=None)
    collection_name: str = Field(default="test_collection")

    def _run(self, query: str, **kwargs: Any) -> str:
        return _STUB_RESUME_CONTEXT

    async def _arun(self, query: str, **kwargs: Any) -> str:
        return _STUB_RESUME_CONTEXT


def pytest_addoption(parser):
    parser.addoption(
        "--real-ai",
        action="store_true",
        default=False,
        help="Run tests that make real AI API calls (requires API keys)",
    )
    parser.addoption(
        "--models",
        default="google_genai:gemini-2.5-flash-lite",
        help="Comma-separated model strings for multi-model tests",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "real_ai: requires live API keys")
    config.addinivalue_line("markers", "slow: multi-model comparison, takes several minutes")
    os.environ.setdefault("LANGCHAIN_PROJECT", "betterresume-tests")


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
def mock_pg_vector_tool():
    tool = _StubPGVectorTool(user_id="test_user_001")
    return tool
