# BetterResume

BetterResume is an open-source tool designed to help users create tailored resumes optimized for ATS (Applicant Tracking System) AI scanners. By leveraging LLMs (Large Language Models) and structured data, BetterResume generates professional resumes customized to specific job descriptions.

---

## Features

- **Custom Resume Generation**: Generate resumes tailored to specific job descriptions using LLMs and RAG (Retrieval-Augmented Generation).
- **Multiple Output Formats**: Supports Word (`.docx`), LaTeX (`.tex`), and PDF (`.pdf`) formats.
- **Data-Driven**: Uses structured data from a CSV file to populate resume sections.
- **Language Support**: Automatically translates resumes into different languages based on user preferences.
- **Skill and Experience Matching**: Extracts relevant skills and experiences from a vector database to align with job descriptions.
- **Extensible**: Easily customizable for additional formats or integrations.

---

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/IanDalton/BetterResume.git
   cd BetterResume
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Ensure you have the following installed:
   - Python 3.9+
   - Microsoft Word (for `.docx` to `.pdf` conversion)
   - `pdflatex` (for LaTeX to PDF conversion)

---

## Usage

### 1. Prepare Your Data
The tool relies on a structured CSV file (`jobs.csv`) to populate resume sections. Ensure your jobs.csv file follows this structure:

| **type**       | **company**       | **location**          | **role**             | **start_date** | **end_date**   | **description**                                                                                                                                                                                                                     |
|-----------------|-------------------|-----------------------|----------------------|----------------|----------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| info           | name              |                       |                      |                |                | Your full name (e.g., "John Doe").                                                                                                                                                                                                 |
| info           | email             |                       |                      |                |                | Your email address (e.g., "johndoe@example.com").                                                                                                                                                                                  |
| info           | phone             |                       |                      |                |                | Your phone number (e.g., "+1 123-456-7890").                                                                                                                                                                                       |
| info           | website           |                       | LinkedIn/GitHub/etc. |                |                | Your personal website or professional profiles (e.g., "https://linkedin.com/in/johndoe").                                                                                                                                          |
| info           | address           |                       |                      |                |                | Your address (e.g., "New York, USA").                                                                                                                                                                                              |
| education      | Institution Name  | Location              |                      | Start Date     | End Date       | Degree or certification details (e.g., "Bachelor of Science in Computer Science").                                                                                                                                                 |
| job            | Company Name      | Location              | Job Title            | Start Date     | End Date       | Job description, including key responsibilities and achievements (e.g., "Developed scalable ETL pipelines, reducing processing time by 40%.").                                                                                     |
| non-profit     | Organization Name | Location              | Volunteer Role       | Start Date     | End Date       | Volunteer work description (e.g., "Led a team of 5 to develop a mobile app for community engagement.").                                                                                                                            |
| project        | Project Name      | Location              | Role                 | Start Date     | End Date       | Project description (e.g., "Built a web app using FastAPI and React to automate resume generation.").                                                                                                                              |
| contract       | Company Name      | Location              | Contract Role        | Start Date     | End Date       | Contract work description (e.g., "Designed and implemented a machine learning pipeline to predict sales trends, increasing accuracy by 30%.").                                                                                     |

### 2. Generate a Resume
Run the following command to generate a resume:
```bash
python bot.py --job job_description.txt
```

- Replace `job_description.txt` with a text file containing the job description.
- The resume will be saved as `resume.pdf` by default.




---

## File Structure

- **`jobs.csv`**: Contains structured data about your personal information, education, and work experience.
- **prompts**: Contains the prompts used for generating and translating resumes.
- **resume**: Contains modules for generating resumes in different formats (Word, LaTeX, etc.).
- **llm**: Contains tools and integrations for interacting with LLMs and vector databases.
- **utils**: Utility functions for file I/O and Word document manipulation.

---

## Customization

### Adding New Resume Formats
To add a new format, create a new writer class in the resume directory by extending the `BaseWriter` class. Implement the `write`, `generate_file`, and `to_pdf` methods.

### Modifying Prompts
Edit the prompt files in the prompts directory to customize how resumes are generated or translated.

---

## Requirements

- Python 3.9+
- Libraries: `langgraph`, `langsmith`, `langchain_openai`, `fastapi`, `chromadb`, `python-docx`, `pandas`, `comtypes`, `pdflatex`.

Install all dependencies using:
```bash
pip install -r requirements.txt
```

---

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests to improve the project.

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.