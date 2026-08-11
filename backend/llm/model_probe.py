"""Live compatibility check for a model string.

The OpenRouter catalog is not sufficient to tell whether a model can serve our
requests. `qwen/qwen3.7-flash`, for example, advertises `tools` *and*
`tool_choice` in `supported_parameters`, yet its only endpoint supports
`tool_choice: "auto"` and nothing else.

The probe runs one request through exactly the production path, including the
`llm.tool_forcing` degrade, so it reports three distinct outcomes: the model
works, the model works but only with an unforced tool choice (`ok=True`,
`forced_tool_choice=False`), or the model does not work at all. Cheap (a handful
of tokens), and it happens when an admin picks the model rather than on a real
user's generation.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from llm.agent import model_settings_for, normalize_model_name
from llm.tool_forcing import forcing_disabled
from llm.tool_forcing import prepare as prepare_model

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
    # False when the model had to be asked (`tool_choice: "auto"`) rather than
    # forced to call its tool. Still usable -- just worth telling the admin.
    forced_tool_choice: bool = True

    @property
    def message(self) -> str:
        if not self.ok:
            return self.detail or "Model check failed"
        if not self.forced_tool_choice:
            return (
                "Model responded correctly, but it rejects forced tool calls; "
                "requests to it will ask for the tool instead of requiring it"
            )
        return "Model responded correctly"


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
            probe_agent.run(
                "Say ready.",
                # Goes through the same preparation as a real run, so a model
                # that rejects forced tool calls degrades here exactly as it
                # would in production -- and is remembered for this process.
                model=prepare_model(resolved),
                model_settings=model_settings_for(resolved),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return ProbeResult(False, f"No response within {int(timeout)}s")
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.info("Model probe failed for %s: %s", model, detail)
        return ProbeResult(False, detail[:500])
    forced = not (isinstance(resolved, str) and forcing_disabled(resolved))
    return ProbeResult(True, forced_tool_choice=forced)
