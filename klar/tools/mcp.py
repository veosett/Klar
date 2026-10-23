"""`klar mcp`: a Model Context Protocol server (stdio, one JSON-RPC message per line) that gives AI agents the Klar
tools directly: check, test, dev, eval, doc, outline, refs, context, patch, fix, fmt, explain, spec.

Each tool runs the `klar` command of the same name and returns its output (the `--json` form where there is one) as
text; `isError` is true when the command exits with a non-zero status. `klarc mcp` (compiler/mcp.klar) answers every
message the same way, character for character (tests/selfhost.py), by running klarc's commands.
"""
import contextlib
import io
import json
import sys

PROTOCOL = "2025-06-18"

INSTRUCTIONS = ("Klar tools. Write Klar with tests next to the code; call klar_dev (check + tests + run) after each "
                "change and follow its `next` field; edit by name with klar_patch; look names up with klar_doc and "
                "klar_outline instead of guessing; klar_spec gives the language reference.")


def _s(desc):
    return {"type": "string", "description": desc}


def _b(desc):
    return {"type": "boolean", "description": desc}


FILE = _s("path of a .klar file")

# name, description, properties, required, argv builder (from the arguments)
TOOLS = [
    ("klar_check", "Type-check a Klar file: diagnostics with codes, positions, hints and machine fixes (JSON).",
     {"file": FILE}, ["file"],
     lambda a: ["check", a["file"], "--json"]),
    ("klar_dev", "One AI-loop step: check, run all tests and run main; compact JSON report with a `next` field.",
     {"file": FILE, "stdin": _s("input for read_line() when main runs"), "run": _b("run main (default true)")},
     ["file"],
     lambda a: ["dev", a["file"], "--json"] + (["--stdin", _str(a, "stdin")] if _str(a, "stdin") else [])
     + (["--no-run"] if a.get("run") is False else [])),
    ("klar_test", "Run the tests, doc-tests and properties of a Klar file (report text).",
     {"file": FILE, "filter": _s("only tests whose name contains this text")}, ["file"],
     lambda a: ["test", a["file"]] + (["-k", _str(a, "filter")] if _str(a, "filter") else [])),
    ("klar_eval", "Evaluate a Klar expression (after optional statements, optionally in the context of a file): its "
                  "value and static type (JSON).",
     {"expression": _s("the expression"), "statements": {"type": "array", "items": {"type": "string"},
                                                          "description": "statements run before it"},
      "file": _s("a .klar file whose declarations are visible")}, ["expression"],
     lambda a: ["eval"] + [x for x in (a.get("statements") if isinstance(a.get("statements"), list) else [])
                           if isinstance(x, str)] + [a["expression"]]
     + (["--in", _str(a, "file")] if _str(a, "file") else []) + ["--json"]),
    ("klar_doc", "Look up a built-in, std or project name: signatures, documentation and tested examples (JSON).",
     {"query": _s("a name such as split, List.sort, std.math"), "file": _s("also search this file's modules")},
     ["query"],
     lambda a: ["doc", a["query"], "--json"] + (["--in", _str(a, "file")] if _str(a, "file") else [])),
    ("klar_outline", "The API of a Klar file and its modules: declarations with signatures and lines (JSON).",
     {"file": FILE}, ["file"],
     lambda a: ["outline", a["file"], "--json"]),
    ("klar_refs", "Every definition and use of a name in a Klar file and its modules (JSON).",
     {"file": FILE, "name": _s("the name")}, ["file", "name"],
     lambda a: ["refs", a["file"], a["name"], "--json"]),
    ("klar_context", "Everything needed to change one function, type or constant without reading files: its source "
                     "and documentation, the signatures it uses, its tests and callers, within a token budget (JSON).",
     {"file": FILE, "name": _s("the function, type or constant (a method: Type.method)"),
      "max_tokens": {"type": "integer", "description": "the budget in tokens (default 2000)"}}, ["file", "name"],
     lambda a: ["context", a["file"], a["name"], "--json"]
     + (["--max-tokens", str(a["max_tokens"])] if isinstance(a.get("max_tokens"), int)
        and not isinstance(a.get("max_tokens"), bool) else [])),
    ("klar_patch", "Edit a Klar file by name with the AI patch protocol, e.g. "
                   "{\"edits\": [{\"replace\": \"fname\", \"with\": \"fn ...\"}]}; written only when it adds no "
                   "errors (JSON report).",
     {"file": FILE, "patch": _s("the patch as JSON text"), "dry_run": _b("only report, do not write")},
     ["file", "patch"],
     lambda a: ["patch", a["file"], a["patch"], "--json"] + (["--dry-run"] if a.get("dry_run") is True else [])),
    ("klar_fix", "Apply the safe machine fixes of the diagnostics to a Klar file (JSON report).",
     {"file": FILE, "dry_run": _b("only report, do not write")}, ["file"],
     lambda a: ["fix", a["file"], "--json"] + (["--dry-run"] if a.get("dry_run") is True else [])),
    ("klar_fmt", "Format a Klar file in place in the canonical layout (JSON report).",
     {"file": FILE}, ["file"],
     lambda a: ["fmt", a["file"], "--json"]),
    ("klar_explain", "Explain a diagnostic code (E0201, R0002, W0401, ...) with an example and the fix.",
     {"code": _s("the code")}, ["code"],
     lambda a: ["explain", a["code"]]),
    ("klar_spec", "The compact Klar language reference for AI authors (syntax, types, effects, std library).",
     {}, [],
     lambda a: ["spec"]),
]


def _str(a, key):
    v = a.get(key)
    return v if isinstance(v, str) and v != "" else None


def tool_list():
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props, "required": req}}
            for name, desc, props, req, _ in TOOLS]


def run_cli(argv):
    """Runs a klar command in this process: (exit status, stdout + stderr)."""
    from ..cli import main as cli_main
    out = io.StringIO()
    code = 0
    old_in, sys.stdin = sys.stdin, io.StringIO("")      # the programs must not read the protocol's messages
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli_main(argv) or 0
            except SystemExit as ex:
                code = ex.code if isinstance(ex.code, int) else 1
    finally:
        sys.stdin = old_in
    return code, out.getvalue()


def call_tool(name, args, runner=run_cli):
    entry = next((t for t in TOOLS if t[0] == name), None)
    if entry is None:
        return None
    _, _, props, required, build = entry
    missing = [r for r in required if not isinstance(args.get(r), str) or args.get(r) == ""]
    if missing:
        return {"content": [{"type": "text", "text": f"missing argument: {missing[0]}"}], "isError": True}
    code, text = runner(build(args))
    return {"content": [{"type": "text", "text": text}], "isError": code != 0}


def handle(msg, runner=run_cli):
    """The response to one message (None for notifications)."""
    from .. import __version__
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    method = msg.get("method")
    mid = msg.get("id")
    if "id" not in msg:
        return None
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if method == "initialize":
        version = params.get("protocolVersion") if isinstance(params.get("protocolVersion"), str) else PROTOCOL
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "klar", "version": __version__}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        name = params.get("name") if isinstance(params.get("name"), str) else ""
        result = call_tool(name, args, runner)
        if result is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool: {name}"}}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def serve(inp, out, runner=run_cli):
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle(msg, runner)
        if resp is not None:
            out.write(dumps(resp) + "\n")
            out.flush()


def cmd_mcp(args):
    serve(sys.stdin, sys.stdout)
    return 0


def register(sub):
    p = sub.add_parser("mcp", help="run a Model Context Protocol server (stdio) with the Klar tools for AI agents")
    p.set_defaults(fn=cmd_mcp)
