"""Sample "cleaned" resume PDF text, used to test extraction without needing a
real binary PDF fixture (this repo's fixtures are plain Python literals -- see
job_descriptions.py/resume_samples.py -- so extraction is tested against the
post-_clean_text() text a real upload would produce, rather than a
hand-authored binary PDF). Covers the two supported input shapes: LinkedIn
"Save to PDF" exports and conventional resumes."""

SAMPLE_LINKEDIN_TEXT_BASIC = """
Jane Doe
Senior Software Engineer at Acme Corp

Contact
jane.doe@example.com
linkedin.com/in/janedoe

Experience
Acme Corp
Senior Software Engineer
Mar 2021 - Present (3 years 4 months)
San Francisco, CA
Led migration to containerized infrastructure, reducing deployment time by 60%.

Education
UC Berkeley
B.S. Computer Science
Sep 2014 - May 2018
"""

# Mirrors the real "Save to PDF" layout: company name, then role, then a
# "<start> - <end> (<duration>)" line, then location, then the bullets. The
# parenthesized duration line is a known extraction trap (small models copy it
# into `description`), so keeping it in the fixture is load-bearing.
SAMPLE_LINKEDIN_TEXT_FULL = """
Jane Doe
Senior Software Engineer | Distributed Systems

Contact
jane.doe@example.com
+1 415 555 0100
linkedin.com/in/janedoe
jane.dev

About
Backend engineer with 8+ years building distributed systems at scale.
Passionate about mentoring and clean architecture.

Experience
Acme Corp
Senior Software Engineer
Mar 2021 - Present (3 years 4 months)
San Francisco, CA
Led migration to containerized infrastructure, reducing deployment time by 60%.
Mentored 3 junior engineers through weekly code reviews.

Beta Inc
Software Engineer
Jun 2018 - Feb 2021 (2 years 9 months)
Remote
Built REST APIs in Python/FastAPI serving 50k req/s with 99.9% uptime.

Gamma LLC
2 years 1 month
Intern
Jun 2016 - Jun 2018 (2 years 1 month)

Education
UC Berkeley
B.S. Computer Science
Sep 2014 - May 2018

Skills
Python
FastAPI
PostgreSQL
Kubernetes

Languages
English (Native)
Spanish (Professional working proficiency)
"""

# A conventional single-column resume (non-LinkedIn): role and company on one
# line, dates on the same line, bullets marked with •.
SAMPLE_CONVENTIONAL_RESUME_TEXT = """
John Smith
Backend Engineer
john.smith@example.com | +1 555 010 0200 | Austin, TX
github.com/johnsmith | johnsmith.dev

SUMMARY
Backend engineer specializing in high-throughput data pipelines.

EXPERIENCE
Backend Engineer, Widget Works — Austin, TX
Jan 2022 - Present
• Designed event-driven ingestion handling 2M events/day on Kafka.
• Cut p99 API latency from 800ms to 120ms by introducing read-through caching.

Junior Developer, Data Co — Remote
Jul 2019 - Dec 2021
• Maintained ETL jobs in Airflow feeding the analytics warehouse.

EDUCATION
B.S. Computer Science, University of Texas at Austin
2015 - 2019
Graduated with honors.

SKILLS
Python, Go, Kafka, PostgreSQL, Docker

LANGUAGES
English (Native), German (B2)
"""
