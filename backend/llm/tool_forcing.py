"""Coping with models that reject a forced tool choice.

Our agents always ask for a forced tool call: structured output is an output
tool and text output is disallowed, so pydantic-ai sends
`tool_choice: "required"`. Some OpenRouter models cannot serve that -- e.g.
`qwen/qwen3.7-flash`, whose only endpoint accepts `tool_choice: "auto"` and
nothing else, so every request 404s with "No endpoints found that support the
provided 'tool_choice' value". The catalog advertises `tool_choice` support for
it, so nothing short of a real request reveals this.

Those models still answer correctly when simply *asked* to use the tool, so
rather than refusing them we degrade: pydantic-ai's
`openai_supports_tool_choice_required` profile flag makes it send `"auto"`
instead, and the agent's own output validation still rejects an answer that
skipped the tool.

Detection is adaptive rather than configured: the first request for such a
model fails, is retried unforced, and the model is remembered for the rest of
the process. That is self-healing across workers and covers models that never
pass through the admin dashboard at all (eval runs pick arbitrary catalog
models), which a stored flag would not.
"""

import logging
from typing import Callable, Optional, Set, Union

from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model
from pydantic_ai.models.wrapper import WrapperModel

logger = logging.getLogger("betterresume.tool_forcing")

# Makes pydantic-ai send tool_choice="auto" where it would send "required".
UNFORCED_PROFILE = {"openai_supports_tool_choice_required": False}

# Model strings observed to reject a forced tool choice, remembered so only the
# first request of a process pays for the discovery.
_UNFORCED_MODELS: Set[str] = set()


def is_tool_forcing_rejection(exc: BaseException) -> bool:
    """Whether `exc` is a provider refusing our forced `tool_choice`.

    Matched on the message rather than the status code: OpenRouter reports it as
    a 404 ("no endpoints found") while a provider reached directly reports a
    400, and both name `tool_choice`.
    """
    return "tool_choice" in str(exc)


def is_openrouter_string(model: Union[str, Model, None]) -> bool:
    return isinstance(model, str) and model.startswith("openrouter:")


def forcing_disabled(model_string: str) -> bool:
    """Whether this model is known to need an unforced tool choice."""
    return model_string in _UNFORCED_MODELS


def remember_unforced(model_string: str) -> None:
    _UNFORCED_MODELS.add(model_string)


def reset_known_models() -> None:
    """Forget what has been learned. For tests."""
    _UNFORCED_MODELS.clear()


def build_openrouter_model(model_string: str, *, forced: bool) -> Model:
    from pydantic_ai.models.openrouter import OpenRouterModel

    name = model_string.split(":", 1)[1]
    return OpenRouterModel(name, profile=None if forced else dict(UNFORCED_PROFILE))


class AdaptiveToolChoiceModel(WrapperModel):
    """Retries once without a forced tool choice when the provider rejects one.

    The retry happens at the model layer, so it re-sends one HTTP request with
    the same messages -- the agent above never sees the failure, and no
    conversation state is rewound.
    """

    def __init__(self, model_string: str, builder: Optional[Callable[..., Model]] = None):
        # Resolved here rather than as a default argument so the builder stays
        # substitutable (tests) and monkeypatchable at the module level.
        self._model_string = model_string
        self._builder = builder or build_openrouter_model
        super().__init__(self._builder(model_string, forced=not forcing_disabled(model_string)))

    async def request(self, messages, model_settings, model_request_parameters):
        try:
            return await self.wrapped.request(messages, model_settings, model_request_parameters)
        except ModelAPIError as exc:
            if forcing_disabled(self._model_string) or not is_tool_forcing_rejection(exc):
                raise
            logger.warning(
                "Model %s rejected a forced tool choice (%s); retrying with tool_choice='auto' "
                "and using it for subsequent requests",
                self._model_string, exc,
            )
            remember_unforced(self._model_string)
            self.wrapped = self._builder(self._model_string, forced=False)
            return await self.wrapped.request(messages, model_settings, model_request_parameters)


def prepare(model: Union[str, Model, None]) -> Union[str, Model, None]:
    """The model to hand pydantic-ai for a run.

    OpenRouter model strings are wrapped so a forced-tool-choice rejection
    degrades instead of failing. Everything else -- other providers, and the
    `Model` instances tests and the eval runner pass -- is returned untouched.
    """
    if not is_openrouter_string(model):
        return model
    return AdaptiveToolChoiceModel(model)
