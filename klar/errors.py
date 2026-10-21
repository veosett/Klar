"""Runtime error type shared by the interpreter and built-ins."""
from .diagnostics import Diagnostic


class KlarRuntimeError(Exception):
    def __init__(self, code, message, span, details=None, stack=None, hint=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.span = span
        self.details = details or []      # list of "name = value" strings
        self.stack = stack or []          # list of (fn_name, call_span)
        self.hint = hint

    def to_diag(self) -> Diagnostic:
        notes = []
        if self.details:
            notes.append("values: " + ", ".join(self.details))
        if self.stack:
            frames = [f"{name} ({sp.short()})" for name, sp in reversed(self.stack)]
            if len(frames) > 8:
                frames = frames[:5] + [f"... {len(frames) - 7} more frames ..."] + frames[-2:]
            notes.append("call stack (innermost first): " + " <- ".join(frames))
        return Diagnostic(self.code, "runtime error", self.message, self.span, self.hint, None, notes)

    def to_dict(self):
        d = self.to_diag().to_dict()
        d["values"] = list(self.details)
        frames = [{"fn": n, "at": sp.to_dict()} for n, sp in reversed(self.stack)]
        if len(frames) > 20:
            frames = frames[:15] + [{"fn": f"... {len(frames) - 20} frames omitted ..."}] + frames[-5:]
        d["stack"] = frames  # innermost first
        d.pop("notes", None)
        return d
