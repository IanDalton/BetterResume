"""Live compatibility check for a model string.

The OpenRouter catalog is not sufficient to tell whether a model can serve our
requests. `qwen/qwen3.7-flash`, for example, advertises `tools` *and*
`tool_choice` in `supported_parameters`, yet its only endpoint supports
`tool_choice: "auto"` and nothing else -- so every real request 404s with
"No endpoints found that support the provided 'tool_choice' value".

Our agents always send `tool_choice: "required"`: structured output is an output
tool and text output is disallowed, so pydantic-ai forces a tool call. The only
reliable way to know a model can do that is to ask it once, which is what this
module does -- cheaply (a handful of tokens), at the moment an admin picks the
model, instead of on a real user's generation.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from llm.agent import model_settings_for, normalize_model_name

logger = logging.getLogger("betterresume.model_probe")

PROBE_TIMEOUT_SECONDS = 45.0


class _ProbeOutput(BaseModel):
    """Structured output, so pydantic-ai forces a tool call exactly as it does
    for `ResumeOutputFormat`."""

    answer: str = Field(description="The single word 'ready'")


# A function tool alongside the output tool, mirroring the generation agent:
# some providers accept a forced choice only when one tool is on the wire.
probe_agent = Agent(
    output_type=_ProbeOutput,
    instructions="Reply by calling the output tool with the answer 'ready'.",
    retries=1,
)


@probe_agent.tool_plain
def probe_ping() -> str:
    """Return the string 'pong'. Only used to give the probe a function tool."""
    return "pong"


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    detail: Optional[str] = None

    @property
    def message(self) -> str:
        return "Model responded correctly" if self.ok else (self.detail or "Model check failed")


async def probe_model(model: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> ProbeResult:
    """Run one minimal forced-tool-call request against `model`.

    Returns `ProbeResult(ok=False, detail=...)` rather than raising: the caller
    (the admin dashboard) wants to report the reason, and the distinction
    between "this model can never work" and "the provider is having a bad
    minute" is the admin's to make.
    """
    resolved = normalize_model_name(model)
    try:
        await asyncio.wait_for(
            probe_agent.run("Say ready.", model=resolved, model_settings=model_settings_for(resolved)),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return ProbeResult(False, f"No response within {int(timeout)}s")
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.info("Model probe failed for %s: %s", model, detail)
        return ProbeResult(False, detail[:500])
    return ProbeResult(True)
