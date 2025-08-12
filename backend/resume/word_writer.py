import os
import logging
from docx import Document
from docx.shared import Cm, Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from typing import Dict, Any
import pandas as pd
from .base_writer import BaseWriter
from utils.word_utils import set_paragraph_font, set_paragraph_format, set_heading_font, add_hyperlink

class WordResumeWriter(BaseWriter):
    """
    A class for generating resumes in Word document format and optionally converting them to PDF.
    Methods
    -------
    write(response: dict, output: str = None, to_pdf: bool = False) -> Union[str, Document]:
        Generates a Word document based on the provided response data and optionally converts it to a PDF.
    generate_file(response: dict, output: str = None) -> Union[str, Document]:
        Creates a Word document with formatted resume content based on the provided response data.
    to_pdf(output: str, src_path: str = None) -> str:
        Converts a Word document to a PDF file using the comtypes library.
    """ 
    def __init__(self, template: str = None, csv_location: str = "jobs.csv"):
        super().__init__(template, csv_location, ".docx")
        self._logger = logging.getLogger("betterresume.writer")

    

    def write(self,response:dict, output: str = None, to_pdf:bool=False):
        file = self.generate_file(response, output.replace(".pdf", ".docx") if output else None)
        self._logger.info("DOCX generated: %s", file if isinstance(file, str) else output)
        if not to_pdf:
            return file
        file = self.to_pdf(output.replace(".docx", ".pdf"), file)
        self._logger.info("PDF generated: %s", file)
        return file

    def generate_file(self,response:dict, output: str = None):
        
        data = self.data
        self.response = response or {}

        # Create the Word document
        
        document = Document()

        # Set reduced margins for the document
        sections = document.sections
        for section in sections:
            section.top_margin = Cm(2)  # Set top margin to 1 cm
            section.bottom_margin = Cm(1)  # Set bottom margin to 1 cm
            section.left_margin = Cm(2)  # Set left margin to 1 cm
            section.right_margin = Cm(2)  # Set right margin to 1 cm

        # Helper safe getters
        def _safe_first(series, default: str = "") -> str:
            try:
                if series is None:
                    return default
                lst = series.to_list() if hasattr(series, "to_list") else list(series)
                return lst[0] if lst else default
            except Exception:
                return default

        resume_section = {}
        try:
            resume_section = (self.response or {}).get("resume_section", {}) or {}
        except Exception:
            resume_section = {}

        # Heading (Name - Title)
        try:
            name_txt = _safe_first(data[data['company'] == 'name']['description'], "")
            title_txt = resume_section.get("title", "")
            heading_txt_parts = [p for p in [name_txt, title_txt] if p]
            if heading_txt_parts:
                heading = document.add_heading(" - ".join(heading_txt_parts), 0)
                set_heading_font(heading, font_name="Times New Roman", font_size=16)
        except Exception as e:
            self._logger.debug("Skipping heading due to missing data: %s", e)
        
        # Address • Phone
        try:
            address_txt = _safe_first(data[data['company'] == 'address']['description'], "")
            phone_txt = _safe_first(data[data['company'] == 'phone']['description'], "")
            parts = [p for p in [address_txt, phone_txt] if p]
            if parts:
                contact_paragraph = document.add_paragraph(" • ".join(parts))
                set_paragraph_font(contact_paragraph)
                set_paragraph_format(contact_paragraph)
        except Exception as e:
            self._logger.debug("Skipping address/phone due to missing data: %s", e)

        # Email • Websites
        try:
            email_txt = _safe_first(data[data['company'] == 'email']['description'], "")
            websites = []
            try:
                websites = data[data["company"] == "website"]["description"].to_list()
            except Exception:
                websites = []
            if email_txt or websites:
                p = document.add_paragraph(f"{email_txt}" + (" • " if email_txt and websites else ""))
                set_paragraph_font(p)
                set_paragraph_format(p)
                for i, website in enumerate([w for w in websites if w]):
                    try:
                        add_hyperlink(p, website, website)
                    except Exception:
                        # Fallback to plain text if hyperlink fails
                        p.add_run(website)
                    if i < len([w for w in websites if w]) - 1:
                        p.add_run(" • ")
        except Exception as e:
            self._logger.debug("Skipping email/websites due to missing data: %s", e)

        # Professional summary
        try:
            summary_txt = resume_section.get("professional_summary", "")
            if summary_txt:
                summary_paragraph = document.add_paragraph(summary_txt)
                set_paragraph_font(summary_paragraph)
                set_paragraph_format(summary_paragraph)
        except Exception as e:
            self._logger.debug("Skipping professional summary: %s", e)

        # Skills
        try:
            skills = resume_section.get("skills", []) or []
            if skills:
                skills_heading = document.add_heading('SKILLS', level=0)
                set_heading_font(skills_heading, font_name="Times New Roman", font_size=11)

                for skill in skills:
                    try:
                        p = document.add_paragraph()
                        p.style = "List Bullet"
                        set_paragraph_font(p)
                        set_paragraph_format(p)
                        name = (skill or {}).get("name", "")
                        desc = (skill or {}).get("description", "")
                        if name:
                            p.add_run(name).bold = True
                        if desc:
                            if name:
                                p.add_run(f" - {desc}")
                            else:
                                p.add_run(desc)
                    except Exception:
                        continue
        except Exception as e:
            self._logger.debug("Skipping skills due to missing data: %s", e)

        # Experience
        try:
            experiences = resume_section.get("experience", []) or []
            if experiences:
                experience_heading = document.add_heading('EXPERIENCE', level=0)
                set_heading_font(experience_heading, font_name="Times New Roman", font_size=11)

                for experience in experiences:
                    try:
                        exp = experience or {}
                        company = exp.get("company", "")
                        location = exp.get("location", "")
                        position = exp.get("position", "")
                        start_date = exp.get("start_date", "")
                        end_date = exp.get("end_date", None)

                        p = document.add_paragraph()
                        set_paragraph_font(p)
                        set_paragraph_format(p)
                        parts_left = []
                        if company:
                            run = p.add_run(company)
                            run.bold = True
                        if location:
                            parts_left.append(location)
                        if position:
                            parts_left.append(position)
                        if parts_left:
                            p.add_run(" • " + " • ".join(parts_left))

                        # Add a tab stop for right alignment
                        try:
                            tab_stop = p.paragraph_format.tab_stops.add_tab_stop(Inches(6.5))  # Adjust width as needed
                            tab_stop.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                        except Exception:
                            pass

                        date_right = None
                        if start_date or (end_date is not None):
                            end_txt = end_date if end_date else 'Present'
                            date_right = f"\t({start_date} - {end_txt})"
                            p.add_run(date_right)

                        desc = exp.get("description", "")
                        if desc:
                            p2 = document.add_paragraph()
                            set_paragraph_font(p2)
                            set_paragraph_format(p2)
                            p2.add_run(desc)
                    except Exception:
                        continue
        except Exception as e:
            self._logger.debug("Skipping experience due to missing data: %s", e)

        # Education and certifications
        try:
            edu_df = None
            try:
                edu_df = data[data["type"] == "education"]
            except Exception:
                edu_df = None
            if edu_df is not None and not edu_df.empty:
                education_heading = document.add_heading('EDUCATION AND CERTIFICATIONS', level=0)
                set_heading_font(education_heading, font_name="Times New Roman", font_size=11)

                for _, edu in edu_df.iterrows():
                    try:
                        company = edu.get('company', '') if isinstance(edu, pd.Series) else ''
                        location = edu.get('location', '') if isinstance(edu, pd.Series) else ''
                        description = edu.get('description', '') if isinstance(edu, pd.Series) else ''
                        left_parts = [p for p in [company, location] if p]
                        left_txt = ", ".join(left_parts) if left_parts else company or location
                        line_txt = left_txt
                        if description:
                            if line_txt:
                                line_txt += f" • {description}"
                            else:
                                line_txt = description
                        p = document.add_paragraph(line_txt)
                        set_paragraph_font(p)
                        set_paragraph_format(p)
                        try:
                            tab_stop = p.paragraph_format.tab_stops.add_tab_stop(Inches(6.5))
                            tab_stop.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                        except Exception:
                            pass
                        def fmt(dt):
                            try:
                                if pd.isna(dt):
                                    return ''
                                if hasattr(dt, 'strftime'):
                                    return dt.strftime('%m/%Y')
                                return str(dt)
                            except Exception:
                                return ''
                        start_txt = fmt(edu.get('start_date') if isinstance(edu, pd.Series) else None)
                        end_raw = edu.get('end_date') if isinstance(edu, pd.Series) else None
                        end_txt = fmt(end_raw) if end_raw is not None else ''
                        if not end_txt:
                            end_txt = 'Present'
                        if start_txt or end_txt:
                            p.add_run(f"\t{start_txt} - {end_txt}")
                    except Exception:
                        continue
        except Exception as e:
            self._logger.debug("Skipping education due to missing data: %s", e)
        if output:
            # Save the Word document
            document.save(output)
            return output
        
        return document
    def to_pdf(self, output: str, src_path: str= None):
        if not output.endswith(".pdf"):
            return output
        # Prefer LibreOffice (Linux container)
        try:
            import subprocess, shutil, sys
            if shutil.which("soffice") and src_path:
                out_dir = os.path.dirname(os.path.abspath(output))
                subprocess.run([
                    "soffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, os.path.abspath(src_path)
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # LibreOffice names file with .pdf in same dir; ensure expected name exists
                generated = os.path.join(out_dir, os.path.splitext(os.path.basename(src_path))[0] + ".pdf")
                if os.path.isfile(generated) and generated != os.path.abspath(output):
                    try:
                        os.replace(generated, output)
                    except Exception:
                        pass
                return output
        except Exception:
            pass
        # Fallback to Windows comtypes if available
        try:
            if not src_path:
                return output
            import comtypes.client  # type: ignore
            word = comtypes.client.CreateObject('Word.Application')
            word.Visible = False
            d = word.Documents.Open(os.path.abspath(src_path))
            d.SaveAs(os.path.abspath(output), FileFormat=17)
            d.Close(); word.Quit()
            return output
        except Exception:
            return output
