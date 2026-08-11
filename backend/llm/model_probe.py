"""Live compatibility check for a model string.

The OpenRouter catalog is not sufficient to tell whether a model can serve our
requests. `qwen/qwen3.7-flash`, for example, advertises `tools` *and*
`tool_choice` in `supported_parameters`, yet its only endpoint supports
`tool_choice: "auto"` and nothing else.

The probe runs one request through exactly the production path, including the
`llm.model_routing` concessions, so it reports what the model needs: it works
as-is, it works but only if we stop forcing its tool choice and/or stop
disabling its reasoning (`ok=True` with `concessions`), or it does not work at
all. Cheap (a handful of tokens), and it happens when an admin picks the model
rather than on a real user's generation.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from llm.agent import RETRIES, model_settings_for, normalize_model_name
from llm.model_routing import Concessions, concessions_for
from llm.model_routing import prepare as prepare_model

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
    # Same output-retry budget as the real agents, so the probe is neither
    # stricter nor more forgiving than the runs it is vouching for.
    retries=RETRIES,
)


@probe_agent.tool_plain
def probe_ping() -> str:
    """Return the string 'pong'. Only used to give the probe a function tool."""
    return "pong"


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    detail: Optional[str] = None
    # What the model needed us to stop asking for. Still usable either way --
    # just worth telling the admin, since both concessions cost something.
    concessions: Concessions = field(default_factory=Concessions)

    @property
    def forced_tool_choice(self) -> bool:
        return not self.concessions.unforced_tool_choice

    @property
    def message(self) -> str:
        if not self.ok:
            return self.detail or "Model check failed"
        if self.concessions:
            return f"Model responded correctly, but it {self.concessions.describe()}"
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
    learned = concessions_for(resolved) if isinstance(resolved, str) else Concessions()
    return ProbeResult(True, concessions=learned)
