import os
from typing import Dict
import pandas as pd
from .base_writer import BaseWriter
import pdflatex

class LatexResumeWriter(BaseWriter):
    """
    LatexResumeWriter is a class for generating resumes in LaTeX format from structured JSON data.
    Methods:
        write(response: dict, output: str = None, to_pdf: bool = False) -> str:
            Generates a LaTeX file from the given response data. Optionally converts the LaTeX file to a PDF.
            Args:
                response (dict): The structured JSON data containing resume information.
                output (str, optional): The output file path for the generated LaTeX or PDF file. Defaults to None.
                to_pdf (bool, optional): Whether to convert the LaTeX file to a PDF. Defaults to False.
            Returns:
                str: The path to the generated LaTeX or PDF file.
        generate_file(response: dict, output: str = None) -> str:
            Creates a LaTeX file based on the provided resume data.
            Args:
                response (dict): The structured JSON data containing resume information.
                output (str, optional): The output file path for the generated LaTeX file. Defaults to None.
            Returns:
                str: The LaTeX content as a string or the path to the generated LaTeX file.
        to_pdf(output: str, src_path: str = None) -> str:
            Converts a LaTeX file to a PDF using the pdflatex command.
            Args:
                output (str): The output file path for the generated PDF.
                src_path (str, optional): The path to the source LaTeX file. Defaults to None.
            Returns:
                str: The path to the generated PDF file.
            Raises:
                RuntimeError: If the LaTeX to PDF conversion fails.
    """
    def __init__(self, template: str = None, csv_location: str = "jobs.csv"):
        super().__init__(template, csv_location, ".tex")


    def write(self, response: dict, output: str = None, to_pdf: bool = False):
        tex_file = self.generate_file(response, output.replace(".pdf", ".tex") if output else None)
        if not to_pdf:
            return tex_file
        return self.to_pdf(output.replace(".tex", ".pdf"), tex_file)

    def generate_file(self, response: dict, output: str = None):
        self.response = response
        data = self.data

        name = data[data['company'] == 'name']['description'].values[0]
        title = response['resume_section']['title']
        address = data[data['company'] == 'address']['description'].values[0]
        phone = data[data['company'] == 'phone']['description'].values[0]
        email = data[data['company'] == 'email']['description'].values[0]
        websites = data[data['company'] == 'website']['description'].tolist()
        websites_names= data[data['company'] == 'website']['role'].tolist()
        websites = dict(zip(websites, websites_names))

        tex = []
        tex.append(r"\documentclass[11pt]{article}")
        tex.append(r"\usepackage[margin=1in]{geometry}")
        tex.append(r"\usepackage{enumitem}")
        tex.append(r"\usepackage[hidelinks]{hyperref}")
        tex.append(r"\usepackage{titlesec}")
        tex.append(r"\usepackage{parskip}")
        tex.append(r"\setlength{\parindent}{0pt}")
        tex.append(r"\begin{document}")

        # Header
        tex.append(r"\begin{center}")
        tex.append(r"\textbf{\LARGE " + name + r"}\\")
        tex.append(r"\textit{" + title + r"}\\")
        tex.append(address + r" \\ " + phone + r" \\ " + email)
        if websites:
            tex.append(r"\\ " + " | ".join([r"\href{" + w + "}{" + websites.get(w, w) + r"}" for w in websites]))
        tex.append(r"\end{center}")
        tex.append(r"\vspace{0.5cm}")

        # Summary
        tex.append(r"\section*{Professional Summary}")
        tex.append(response["resume_section"]["professional_summary"])

        # Skills
        tex.append(r"\section*{Skills}")
        tex.append(r"\begin{itemize}[leftmargin=*]")
        for skill in response["resume_section"].get("skills", []):
            tex.append(r"\item \textbf{" + skill["name"] + r"} -- " + skill["description"])
        tex.append(r"\end{itemize}")

        # Experience
        tex.append(r"\section*{Experience}")
        for exp in response["resume_section"].get("experience", []):
            tex.append(r"\textbf{" + exp["position"] + r"} \hfill " + exp["start_date"] + " -- " + exp["end_date"])
            tex.append(r"\\" + exp["company"] + ", " + exp["location"])
            tex.append(r"\begin{itemize}[leftmargin=*]")
            tex.append(r"\item " + exp["description"])
            tex.append(r"\end{itemize}")

        # Education
        tex.append(r"\section*{Education and Certifications}")
        for _, edu in data[data["type"] == "education"].iterrows():
            dates = edu["start_date"].strftime('%m/%Y') + " -- " + (edu["end_date"].strftime('%m/%Y') if pd.notnull(edu["end_date"]) else "Present")
            tex.append(r"\textbf{" + edu["company"] + r"} \hfill " + dates)
            tex.append(r"\\" + edu["location"] + r" -- " + edu["description"])

        tex.append(r"\end{document}")

        tex_content = "\n".join(tex)

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(tex_content)
            return output

        return tex_content

    def to_pdf(self, output: str, src_path: str = None):

        try:
            import subprocess
            subprocess.run(["pdflatex", src_path], check=True)

            return output

        except Exception as e:
            raise RuntimeError("LaTeX to PDF conversion failed") from e
