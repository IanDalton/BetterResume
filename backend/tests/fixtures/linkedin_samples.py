"""Sample "cleaned" LinkedIn PDF export text, used to test extraction without
needing a real binary PDF fixture (this repo's fixtures are plain Python
literals -- see job_descriptions.py/resume_samples.py -- so extraction is
tested against the post-_clean_text() text a real export would produce,
rather than a hand-authored binary PDF)."""

SAMPLE_LINKEDIN_TEXT_BASIC = """
Jane Doe
Senior Software Engineer at Acme Corp

Contact
jane.doe@example.com
linkedin.com/in/janedoe

Experience
Senior Software Engineer
Acme Corp
Mar 2021 - Present
San Francisco, CA
Led migration to containerized infrastructure, reducing deployment time by 60%.

Education
UC Berkeley
B.S. Computer Science
Sep 2014 - May 2018
"""

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
Senior Software Engineer
Acme Corp
Mar 2021 - Present
San Francisco, CA
Led migration to containerized infrastructure, reducing deployment time by 60%.
Mentored 3 junior engineers through weekly code reviews.

Software Engineer
Beta Inc
Jun 2018 - Feb 2021
Remote
Built REST APIs in Python/FastAPI serving 50k req/s with 99.9% uptime.

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
