"""Regression coverage for the resume result-cache signature.

Before this fix, `_build_result_signature` hashed `agent.DEFAULT_MODEL` -- the
import-time env constant -- instead of the effective, runtime-configured
generation model. Once the model became admin-configurable via `app_settings`,
that made the cache key insensitive to model changes: an admin promoting a new
model wouldn't bust the cache for an unchanged (job description, CSV) pair, so
regenerating would silently keep serving the old model's cached output and no
`generation_events` row would be written. See CLAUDE.md / the design doc for
the full failure scenario.
"""

from unittest.mock import patch

from api.schemas import ResumeRequest
from api.utils import _build_result_signature
from llm import model_config


def _cfg(primary: str) -> model_config.ModelConfig:
    return model_config.ModelConfig(
        generation=model_config.TaskModels(primary, None),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
    )


def test_signature_changes_when_configured_generation_model_changes():
    """Two generations of the identical job description + CSV must not share a
    result-cache entry when the admin-configured generation model differs."""
    req = ResumeRequest(job_description="Backend engineer role", format="word")
    csv_hash = "same-csv-hash"
    job_hash = "same-job-hash"

    with patch("llm.agent.get_model_config", return_value=_cfg("openrouter:model-a")):
        sig_a = _build_result_signature(req, csv_hash, job_hash)

    with patch("llm.agent.get_model_config", return_value=_cfg("openrouter:model-b")):
        sig_b = _build_result_signature(req, csv_hash, job_hash)

    assert sig_a != sig_b


def test_signature_stable_when_configured_generation_model_unchanged():
    """Same inputs + same configured model must reproduce the same signature,
    so genuinely-unchanged requests still hit the cache."""
    req = ResumeRequest(job_description="Backend engineer role", format="word")
    csv_hash = "same-csv-hash"
    job_hash = "same-job-hash"

    with patch("llm.agent.get_model_config", return_value=_cfg("openrouter:model-a")):
        sig_1 = _build_result_signature(req, csv_hash, job_hash)
        sig_2 = _build_result_signature(req, csv_hash, job_hash)

    assert sig_1 == sig_2


def test_cache_payload_records_effective_model_not_default_model_constant():
    """`_cache_payload` must record the model actually used for this result,
    not the stale `agent.DEFAULT_MODEL` import-time constant."""
    from api.routers.resume import _cache_payload

    req = ResumeRequest(job_description="Backend engineer role", format="word")
    payload = _cache_payload(
        req, "word", {"resume_section": {}}, "render-sig", "result-sig",
        "csv-hash", None, "job-hash", model="openrouter:configured/model",
    )
    assert payload["model"] == "openrouter:configured/model"
