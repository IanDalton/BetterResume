"""Coping with OpenRouter routing constraints a given model cannot satisfy.

Every OpenRouter request we make carries three demands beyond the prompt:

* `provider.require_parameters: true` -- only route to endpoints that accept
  everything we send (added because providers that silently ignore our
  tool-call parameters return malformed arguments and burn the agent's retries)
* `reasoning: {enabled: false}` -- don't pay for reasoning tokens we discard
* `tool_choice: "required"` -- structured output is an output tool and text
  output is disallowed, so pydantic-ai forces a tool call

`require_parameters` turns each of the other two into a hard routing filter, and
plenty of perfectly good models cannot satisfy one of them:

* 83 of OpenRouter's 333 tool-capable models take no `reasoning` parameter at
  all, so disabling reasoning leaves no eligible endpoint: 404 "No endpoints
  found that can handle the requested parameters" (e.g.
  `qwen/qwen3-coder-30b-a3b-instruct`, `mistralai/mistral-small-3.2-24b-instruct`).
  Others require it: 400 "Reasoning is mandatory for this endpoint and cannot be
  disabled" (e.g. `openai/gpt-5-nano`, `openai/gpt-oss-120b`).
* Some accept `tool_choice: "auto"` only: 404 "No endpoints found that support
  the provided 'tool_choice' value" (e.g. `qwen/qwen3.7-flash`).

Neither is visible in the catalog -- `supported_parameters` is the union across
endpoints and does not describe which *values* an endpoint honours. So each
demand is dropped on demand: the failing request is retried without it and the
model is remembered for the rest of the process. Both are optimisations, not
correctness requirements -- the agent's own output validation still rejects an
answer that skipped its tools -- so trading one away beats failing the request.

Detection is adaptive rather than stored: it self-heals across workers and
covers models that never pass through the admin dashboard (eval runs pick
arbitrary catalog models), which a persisted flag would not.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Union

from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model
from pydantic_ai.models.wrapper import WrapperModel

logger = logging.getLogger("betterresume.model_routing")

# Makes pydantic-ai send tool_choice="auto" where it would send "required".
UNFORCED_PROFILE = {"openai_supports_tool_choice_required": False}

# The setting dropped for models that will not run with reasoning disabled.
REASONING_SETTING = "openrouter_reasoning"


@dataclass
class Concessions:
    """What a model needs us to stop asking for."""

    unforced_tool_choice: bool = False
    allow_reasoning: bool = False

    def describe(self) -> str:
        parts = []
        if self.unforced_tool_choice:
            parts.append("asks for its tool instead of requiring it (rejects a forced tool choice)")
        if self.allow_reasoning:
            parts.append("runs with reasoning enabled (its endpoints will not accept it disabled)")
        return "; ".join(parts)

    def __bool__(self) -> bool:
        return self.unforced_tool_choice or self.allow_reasoning


_LEARNED: Dict[str, Concessions] = {}


def concessions_for(model_string: str) -> Concessions:
    """What has been learned about this model so far."""
    return _LEARNED.get(model_string) or Concessions()


def remember(model_string: str, **flags: bool) -> None:
    learned = _LEARNED.setdefault(model_string, Concessions())
    for name, value in flags.items():
        setattr(learned, name, value)


def reset_known_models() -> None:
    """Forget what has been learned. For tests."""
    _LEARNED.clear()


def is_tool_forcing_rejection(exc: BaseException) -> bool:
    """Whether `exc` is a provider refusing our forced `tool_choice`.

    Matched on the message rather than the status code: OpenRouter reports it as
    a 404 ("no endpoints found") while a provider reached directly reports a
    400, and both name `tool_choice`.
    """
    return "tool_choice" in str(exc)


def is_reasoning_rejection(exc: BaseException) -> bool:
    """Whether `exc` is a provider refusing to run with reasoning disabled.

    Two shapes: an explicit "reasoning is mandatory", and the generic "no
    endpoints found that can handle the requested parameters" that
    `require_parameters` produces when no endpoint takes a `reasoning`
    parameter. The generic one names no parameter, but reasoning is the only
    optional one we add, so it is the thing to drop.
    """
    message = str(exc).lower()
    return "reasoning" in message or "requested parameters" in message


def is_openrouter_string(model: Union[str, Model, None]) -> bool:
    return isinstance(model, str) and model.startswith("openrouter:")


def build_openrouter_model(model_string: str, *, forced: bool) -> Model:
    from pydantic_ai.models.openrouter import OpenRouterModel

    name = model_string.split(":", 1)[1]
    return OpenRouterModel(name, profile=None if forced else dict(UNFORCED_PROFILE))


class AdaptiveRoutingModel(WrapperModel):
    """Retries a rejected request with one demand dropped, and remembers which.

    The retry happens at the model layer, so it re-sends one HTTP request with
    the same messages -- the agent above never sees the failure, and no
    conversation state is rewound. At most one concession is made per attempt,
    so a model that needs both is discovered in two.
    """

    def __init__(self, model_string: str, builder: Optional[Callable[..., Model]] = None):
        # Resolved here rather than as a default argument so the builder stays
        # substitutable (tests) and monkeypatchable at the module level.
        self._model_string = model_string
        self._builder = builder or build_openrouter_model
        super().__init__(self._build())

    def _build(self) -> Model:
        return self._builder(
            self._model_string,
            forced=not concessions_for(self._model_string).unforced_tool_choice,
        )

    def _request_settings(self, model_settings):
        # Named to avoid pydantic-ai's `Model._settings` attribute, which a
        # method called `_settings` would be shadowed by.
        if not concessions_for(self._model_string).allow_reasoning:
            return model_settings
        remaining = {k: v for k, v in (model_settings or {}).items() if k != REASONING_SETTING}
        return remaining or None

    def _concede(self, exc: BaseException) -> bool:
        """Record one new concession this error calls for. False if none applies."""
        learned = concessions_for(self._model_string)
        if is_tool_forcing_rejection(exc) and not learned.unforced_tool_choice:
            flag = "unforced_tool_choice"
        elif is_reasoning_rejection(exc) and not learned.allow_reasoning:
            flag = "allow_reasoning"
        else:
            return False
        remember(self._model_string, **{flag: True})
        logger.warning(
            "Model %s rejected our request (%s); retrying with %s and keeping that for later requests",
            self._model_string, exc, flag,
        )
        return True

    async def request(self, messages, model_settings, model_request_parameters):
        # One attempt per concession available, plus the original.
        for _ in range(3):
            try:
                return await self.wrapped.request(
                    messages, self._request_settings(model_settings), model_request_parameters
                )
            except ModelAPIError as exc:
                if not self._concede(exc):
                    raise
                self.wrapped = self._build()
        raise AssertionError("unreachable: every concession was already made")  # pragma: no cover


def prepare(model: Union[str, Model, None]) -> Union[str, Model, None]:
    """The model to hand pydantic-ai for a run.

    OpenRouter model strings are wrapped so a rejected routing demand degrades
    instead of failing. Everything else -- other providers, and the `Model`
    instances tests and the eval runner pass -- is returned untouched.
    """
    if not is_openrouter_string(model):
        return model
    return AdaptiveRoutingModel(model)
