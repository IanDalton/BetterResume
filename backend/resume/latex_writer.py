import os
import logging
import shutil
from typing import Dict, Optional
import pandas as pd
from .base_writer import BaseWriter
from models.resume import ResumeOutputFormat
import pdflatex

def _latex_escape(text: str) -> str:
    """Escape LaTeX special characters in arbitrary text.

    Characters:  & % $ # _ { } ~ ^ \
    ~ and ^ have no simple single-char escapes; use \textasciitilde{} and \textasciicircum{}
    Backslashes are doubled.
    """
    if text is None:
        return ""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    out = []
    for ch in str(text):
        out.append(replacements.get(ch, ch))
    return "".join(out)

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
    def __init__(self, template: str = None, csv_location: str = "jobs.csv", profile_image_path: Optional[str] = None):
        super().__init__(template, csv_location, ".tex", profile_image_path=profile_image_path)
        self._logger = logging.getLogger("betterresume.writer")


    def write(self, response: ResumeOutputFormat, output: str = None, to_pdf: bool = False):
        tex_file = self.generate_file(response, output.replace(".pdf", ".tex") if output else None)
        self._logger.info("LaTeX file generated: %s", tex_file)
        if not to_pdf:
            return tex_file
        pdf = self.to_pdf(output.replace(".tex", ".pdf"), tex_file)
        self._logger.info("PDF generated: %s", pdf)
        return pdf

    def generate_file(self, response: ResumeOutputFormat, output: str = None):
        self.response = response
        data = self.data
        # Safe accessors for optional info rows
        def _safe_first(df, default=""):
            try:
                return df.values[0]
            except Exception:
                return default
        name = _latex_escape(_safe_first(data[data['company'] == 'name']['description'], ""))
        title = _latex_escape(response.resume_section.title)
        address = _latex_escape(_safe_first(data[data['company'] == 'address']['description'], ""))
        phone = _latex_escape(_safe_first(data[data['company'] == 'phone']['description'], ""))
        email = _latex_escape(_safe_first(data[data['company'] == 'email']['description'], ""))
        websites = data[data['company'] == 'website']['description'].tolist()
        websites_names= data[data['company'] == 'website']['role'].tolist()
        websites = {w: _latex_escape(n) for w, n in zip(websites, websites_names)}

        tex = []
        tex.append(r"\documentclass[11pt]{article}")
        tex.append(r"\usepackage[margin=1in]{geometry}")
        tex.append(r"\usepackage{graphicx}")
        tex.append(r"\usepackage{enumitem}")
        tex.append(r"\usepackage[hidelinks]{hyperref}")
        tex.append(r"\usepackage{titlesec}")
        tex.append(r"\usepackage{parskip}")
        tex.append(r"\setlength{\parindent}{0pt}")
        tex.append(r"\begin{document}")

        # Header
        profile_path = getattr(self, "profile_image_path", None)
        image_basename = None
        if profile_path and os.path.isfile(profile_path):
            try:
                ext = os.path.splitext(profile_path)[1].lower()
                if ext not in (".png", ".jpg", ".jpeg"):
                    raise ValueError(f"Unsupported LaTeX image format: {ext}")
                normalized_ext = ".jpg" if ext == ".jpeg" else ext
                image_basename = f"profilephoto{normalized_ext}"
                if output:
                    dest_dir = os.path.dirname(os.path.abspath(output)) or "."
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_path = os.path.join(dest_dir, image_basename)
                    if os.path.abspath(profile_path) != dest_path:
                        shutil.copyfile(profile_path, dest_path)
                else:
                    image_basename = os.path.abspath(profile_path)
            except Exception as exc:
                self._logger.warning("Skipping profile image for LaTeX: %s", exc)
                image_basename = None
        elif profile_path:
            self._logger.debug("Profile image path not found: %s", profile_path)

        if image_basename:
            tex.append(r"\begin{minipage}[t]{0.25\textwidth}")
            tex.append(r"\centering")
            tex.append(r"\includegraphics[width=1.5in,keepaspectratio]{" + image_basename.replace('\\', '/') + r"}")
            tex.append(r"\end{minipage}\hfill")
            tex.append(r"\begin{minipage}[t]{0.72\textwidth}")
            tex.append(r"\raggedright")
            tex.append(r"\textbf{\LARGE " + name + r"}\\")
            if title:
                tex.append(r"\textit{" + title + r"}\\")
            contact_parts = [p for p in [address, phone, email] if p]
            if contact_parts:
                tex.append(r" \\ ".join(contact_parts))
            if websites:
                tex.append(r"\\ " + " | ".join([r"\href{" + w + "}{" + websites.get(w, w) + r"}" for w in websites]))
            tex.append(r"\end{minipage}")
        else:
            tex.append(r"\begin{center}")
            tex.append(r"\textbf{\LARGE " + name + r"}\\")
            if title:
                tex.append(r"\textit{" + title + r"}\\")
            contact_parts = [p for p in [address, phone, email] if p]
            if contact_parts:
                tex.append(r" \\ ".join(contact_parts))
            if websites:
                tex.append(r"\\ " + " | ".join([r"\href{" + w + "}{" + websites.get(w, w) + r"}" for w in websites]))
            tex.append(r"\end{center}")
        tex.append(r"\vspace{0.5cm}")

        # Summary
        tex.append(r"\section*{Professional Summary}")
        tex.append(_latex_escape(response.resume_section.professional_summary))

        # Skills
        tex.append(r"\section*{Skills}")
        tex.append(r"\begin{itemize}[leftmargin=*]")
        for skill in response.resume_section.skills:
            tex.append(r"\item \textbf{" + _latex_escape(skill.name) + r"} -- " + _latex_escape(skill.description))
        tex.append(r"\end{itemize}")

        # Experience
        tex.append(r"\section*{Experience}")
        for exp in response.resume_section.experience:
            tex.append(r"\textbf{" + _latex_escape(exp.position) + r"} \hfill " + _latex_escape(exp.start_date) + " -- " + _latex_escape(exp.end_date))
            tex.append(r"\\" + _latex_escape(exp.company) + ", " + _latex_escape(exp.location))
            tex.append(r"\begin{itemize}[leftmargin=*]")
            tex.append(r"\item " + _latex_escape(exp.description))
            tex.append(r"\end{itemize}")

        # Education
        tex.append(r"\section*{Education and Certifications}")
        for edu in response.resume_section.education:
            tex.append(r"\textbf{" + _latex_escape(edu.institution) + r"} \hfill " + _latex_escape(edu.dates))
            tex.append(r"\\" + _latex_escape(edu.degree))

        tex.append(r"\end{document}")

        tex_content = "\n".join(tex)
        # Safety net: in case any raw '&' slipped through (e.g., model output concatenated without escaping)
        # escape ampersands not already escaped. Avoid touching '\\&'.
        import re
        tex_content = re.sub(r'(?<!\\)&', r'\\&', tex_content)

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(tex_content)
            return output

        return tex_content

    def to_pdf(self, output: str, src_path: str = None):
        try:
            import subprocess, os
            # Use pdflatex with explicit output directory to avoid cwd dependence
            out_dir = os.path.dirname(os.path.abspath(output))
            src_abs = os.path.abspath(src_path) if src_path else None
            # pdflatex will write PDF next to the .tex when using -output-directory
            subprocess.run(["pdflatex", "-interaction=nonstopmode", f"-output-directory={out_dir}", src_abs], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Ensure expected name exists; move if needed
            generated = os.path.join(out_dir, os.path.splitext(os.path.basename(src_abs))[0] + ".pdf")
            if os.path.isfile(generated) and os.path.abspath(output) != generated:
                try:
                    os.replace(generated, output)
                except Exception:
                    pass
            return output
        except Exception as e:
            raise RuntimeError("LaTeX to PDF conversion failed") from e
