from models.job_experience import JobExperience
from models.resume_section import ResumeSection
from models.skill import Skill


def _experience(position: str, start_date: str, end_date: str) -> JobExperience:
    return JobExperience(
        position=position,
        company="Acme Corp",
        location="Remote",
        start_date=start_date,
        end_date=end_date,
        description=(
            "Built and shipped features using Python and FastAPI, "
            "improving throughput by 30% and reducing latency."
        ),
    )


def _section(experience: list[JobExperience]) -> ResumeSection:
    return ResumeSection(
        title="Software Engineer",
        professional_summary=(
            "Experienced engineer with a strong background in distributed systems and Python. "
            "Led multiple teams and delivered high-impact projects at scale."
        ),
        experience=experience,
        skills=[Skill(name="Python", description="Used daily in production systems")],
        education=[],
    )


def test_experience_sorted_most_recent_end_date_first():
    section = _section([
        _experience("Oldest", "01/2015", "12/2017"),
        _experience("Newest", "01/2021", "06/2023"),
        _experience("Middle", "01/2018", "12/2020"),
    ])
    assert [e.position for e in section.experience] == ["Newest", "Middle", "Oldest"]


def test_present_end_date_sorts_first():
    section = _section([
        _experience("Past", "01/2018", "12/2020"),
        _experience("Current", "01/2021", "Present"),
    ])
    assert section.experience[0].position == "Current"


def test_already_sorted_experience_unchanged():
    section = _section([
        _experience("Newest", "01/2021", "06/2023"),
        _experience("Oldest", "01/2015", "12/2017"),
    ])
    assert [e.position for e in section.experience] == ["Newest", "Oldest"]


def test_single_experience_preserved():
    section = _section([_experience("Only", "01/2021", "Present")])
    assert [e.position for e in section.experience] == ["Only"]
