"""Pre-built valid ResumeOutputFormat instances for use in unit tests (no AI calls needed)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.resume import ResumeOutputFormat
from models.resume_section import ResumeSection
from models.job_experience import JobExperience
from models.skill import Skill
from models.education import Education


def build_senior_swe_resume() -> ResumeOutputFormat:
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
                        "- Mentored 3 junior engineers through weekly code reviews and pairing sessions"
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
                    description="Kafka and Kubernetes deployments across 5 production microservices",
                ),
                Skill(
                    name="SQL / PostgreSQL",
                    description="Optimized complex queries on 100M+ row tables to <50ms p99",
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
