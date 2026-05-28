from dataclasses import dataclass
from typing import List, Optional

from .schema_evaluator import SchemaEvaluationResult
from .ats_evaluator import ATSEvaluationResult
from .llm_judge import LLMJudgeResult


@dataclass
class ResumeEvaluationReport:
    model: str
    jd_name: str
    schema: SchemaEvaluationResult
    ats: ATSEvaluationResult
    llm_judge: Optional[LLMJudgeResult] = None

    @property
    def composite_score(self) -> float:
        if self.llm_judge:
            return round(
                0.40 * self.schema.score
                + 0.35 * self.ats.score
                + 0.25 * self.llm_judge.overall_score,
                3,
            )
        return round(0.53 * self.schema.score + 0.47 * self.ats.score, 3)

    def print_summary(self) -> None:
        status = "PASS" if self.schema.passed else "FAIL"
        print(f"\n{'=' * 60}")
        print(f"Model: {self.model} | JD: {self.jd_name} | [{status}]")
        print(f"Composite Score: {self.composite_score:.2f}")
        schema_detail = "OK" if self.schema.passed else f"ERRORS: {self.schema.errors}"
        print(f"  Schema:    {self.schema.score:.2f} ({schema_detail})")
        print(f"  ATS:       {self.ats.score:.2f} (coverage={self.ats.keyword_coverage:.2f})")
        if self.llm_judge:
            j = self.llm_judge
            print(f"  LLM Judge: {j.overall_score:.2f}")
            print(
                f"    relevance={j.relevance_score:.2f}  "
                f"quality={j.quality_score:.2f}  "
                f"coherence={j.coherence_score:.2f}"
            )
            print(f"    Reasoning: {j.reasoning}")
        if self.schema.warnings:
            print(f"  Warnings: {self.schema.warnings}")
        if self.ats.missing_keywords[:5]:
            print(f"  Missing keywords (top 5): {self.ats.missing_keywords[:5]}")


def print_comparison_table(reports: List[ResumeEvaluationReport]) -> None:
    sorted_reports = sorted(reports, key=lambda r: r.composite_score, reverse=True)
    print("\n\n=== MULTI-MODEL COMPARISON ===")
    print(f"{'Model':<48} {'Schema':>7} {'ATS':>7} {'Judge':>7} {'Composite':>10}")
    print("-" * 83)
    for r in sorted_reports:
        judge_str = f"{r.llm_judge.overall_score:.2f}" if r.llm_judge else " N/A"
        schema_flag = "" if r.schema.passed else " !"
        print(
            f"{r.model:<48} {r.schema.score:>7.2f}{schema_flag:<1} "
            f"{r.ats.score:>7.2f} {judge_str:>7} {r.composite_score:>10.2f}"
        )
