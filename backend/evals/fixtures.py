"""Deterministic inputs for evaluation runs.

Shared by the pytest integration tests and the admin dashboard's eval runner,
so a dashboard run and a CLI run measure exactly the same thing.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

JD_SOFTWARE_ENGINEER_SENIOR = """
Senior Software Engineer – Platform Team
Acme Corp, San Francisco, CA

We are looking for a Senior Software Engineer to join our Platform team.

Requirements:
- 7+ years Python, distributed systems (Kafka, Kubernetes)
- Strong SQL, experience with CI/CD pipelines
- Experience mentoring junior engineers
- Docker, microservices architecture

Responsibilities:
- Design and implement scalable microservices handling 10M+ events/day
- Lead technical reviews and write Architecture Decision Records (ADRs)
- Optimize SQL query performance (target: <50ms p99 latency)
- Mentor junior engineers through code reviews
"""

JD_DATA_ANALYST_JUNIOR = """
Junior Data Analyst – Growth Team
StartupXYZ, Remote

We are looking for a data-driven analyst to support our growth initiatives.

Requirements:
- 2+ years SQL, Python (pandas, matplotlib, numpy)
- Experience with Tableau or Looker for dashboards
- Basic statistics and A/B testing knowledge
- Nice to have: dbt, Airflow, BigQuery

Responsibilities:
- Build and maintain reporting dashboards
- Analyze user funnel metrics and identify drop-off points
- Partner with product and engineering on experiment design
"""

JD_PRODUCT_MANAGER = """
Product Manager – Consumer Mobile
BigCo, New York, NY

We are hiring a Product Manager to lead our consumer mobile experience.

Requirements:
- 5+ years PM experience in consumer products
- Experience with A/B testing, OKR frameworks, and roadmap planning
- Proficiency with Jira, Figma, and stakeholder communication
- MBA preferred but not required

Responsibilities:
- Define and prioritize product roadmap in collaboration with engineering and design
- Run A/B tests to validate product hypotheses
- Lead cross-functional teams of 10+ people
- Report on OKRs and present to executive leadership
"""


STUB_RESUME_CONTEXT = """\
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
        return [(STUB_RESUME_CONTEXT, 0.1)]

    async def aadd_documents(self, documents: List[str], ids: List[str], user_id: str) -> str:
        self.added.extend(zip(ids, documents))
        return "Documents added successfully."

    async def adelete_user_documents(self, user_id: str) -> str:
        self.deleted_users.append(user_id)
        return "Deleted"

    async def acount_user_documents(self, user_id: str) -> int:
        return len(self.added)


@dataclass(frozen=True)
class JDFixture:
    id: str
    label: str
    text: str


JD_FIXTURES: Dict[str, JDFixture] = {
    "senior_swe": JDFixture("senior_swe", "Senior Software Engineer", JD_SOFTWARE_ENGINEER_SENIOR),
    "junior_analyst": JDFixture("junior_analyst", "Junior Data Analyst", JD_DATA_ANALYST_JUNIOR),
    "product_manager": JDFixture("product_manager", "Product Manager", JD_PRODUCT_MANAGER),
}

CUSTOM_JD_ID = "custom"


def list_fixtures() -> List[dict]:
    return [
        {"id": f.id, "label": f.label, "preview": " ".join(f.text.split())[:160]}
        for f in JD_FIXTURES.values()
    ]
