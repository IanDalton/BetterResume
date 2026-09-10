"""Parsed resume PDF -> ResumeOutputFormat for the analysis pipeline."""

import pytest

from utils.imported_resume import NoExperienceError, imported_to_resume, to_resume_date
from utils.resume_import import ImportedEntry, ImportedLanguage, ImportedProfileFields, ResumeImportResult


@pytest.mark.parametrize("raw,expected", [
    ("01/03/2021", "03/2021"),      # the import prompt's DD/MM/YYYY
    ("03/2021", "03/2021"),
    ("2021-03-15", "03/2021"),
    ("2021-03", "03/2021"),
    ("March 2021", "03/2021"),
    ("Mar  2021", "03/2021"),
    ("2021", "01/2021"),
    ("present", "present"),
    ("Actualidad", "Actualidad"),
    ("", ""),
    (None, ""),
    ("sometime in 2019 or so", "01/2019"),
    ("??/2019", "01/2019"),
    ("n/a", "n/a"),  # no digits: treated as an ongoing marker, like JobExperience does
])
def test_to_resume_date(raw, expected):
    assert to_resume_date(raw) == expected


def _parsed(**overrides) -> ResumeImportResult:
    base = dict(
        profile=ImportedProfileFields(headline="Backend Engineer", summary="Builds APIs."),
        experience=[
            ImportedEntry(type="job", company="Acme", role="Engineer", location="Remote",
                          start_date="01/06/2018", end_date="01/02/2021", description="- Built APIs"),
            ImportedEntry(type="job", company="Beta", role="Senior Engineer",
                          start_date="01/03/2021", end_date="present", description="- Led platform"),
        ],
        education=[ImportedEntry(type="education", company="MIT", role="B.S. CS", start_date="2014", end_date="2018", description="")],
        skills=["Python", " Kubernetes "],
        languages=[ImportedLanguage(name="English", proficiency="C2")],
    )
    base.update(overrides)
    return ResumeImportResult(**base)


def test_converts_every_section_and_sorts_experience_most_recent_first():
    resume = imported_to_resume(_parsed(), language="es")
    section = resume.resume_section
    assert resume.language == "es"
    assert section.title == "Backend Engineer"
    assert section.professional_summary == "Builds APIs."
    assert [e.company for e in section.experience] == ["Beta", "Acme"]
    assert section.experience[0].end_date == "present"
    assert section.experience[1].start_date == "06/2018"
    assert [s.name for s in section.skills] == ["Python", "Kubernetes"]
    assert section.education[0].institution == "MIT"
    assert section.education[0].dates == "01/2014 - 01/2018"
    assert section.languages[0].name == "English"


def test_title_falls_back_to_the_latest_role():
    resume = imported_to_resume(_parsed(profile=ImportedProfileFields()))
    assert resume.resume_section.title == "Engineer"  # first entry as parsed, before sorting


def test_a_resume_without_skills_is_still_scoreable():
    resume = imported_to_resume(_parsed(skills=[]))
    assert resume.resume_section.skills == []
    assert resume.model_dump()["resume_section"]["experience"]


def test_no_experience_is_rejected():
    with pytest.raises(NoExperienceError):
        imported_to_resume(_parsed(experience=[]))
