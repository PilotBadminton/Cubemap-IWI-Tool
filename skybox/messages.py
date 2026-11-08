"""Language-independent messages shared by the engine and desktop interface."""
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / "locales" / "messages.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Message:
    code: str
    params: dict = field(default_factory=dict)
    detail: str = ""

    def render(self, language):
        values = {key: value.render(language) if isinstance(value, Message) else value
                  for key, value in self.params.items()}
        text = catalog()[self.code][language].format(**values)
        return text + ("\n" + self.detail if self.detail else "")


@dataclass(frozen=True)
class Progress:
    message: Message
    done: int = 0
    total: int = 1


def msg(code, **params):
    return Message(code, params)


def exception_message(error):
    from .models import ToolError
    if isinstance(error, ToolError):
        return error.message
    if isinstance(error, OSError):
        return Message("error.os", {"path": str(error.filename or "")}, str(error))
    return Message("error.unexpected", detail=str(error))
