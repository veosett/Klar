// Klar for VS Code: starts the Klar language server (`python -m klar lsp`, or `klarc lsp` without Python when
// "klar.klarcPath" is set) and adds a few commands.
const path = require("path");
const fs = require("fs");
const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

let client = null;

function settings() {
  const cfg = vscode.workspace.getConfiguration("klar");
  let python = cfg.get("pythonPath") || (process.platform === "win32" ? "python" : "python3");
  let root = cfg.get("compilerPath") || "";
  if (!root) {
    // a checkout of the Klar repository opened as the workspace: use its compiler
    for (const folder of vscode.workspace.workspaceFolders || []) {
      if (fs.existsSync(path.join(folder.uri.fsPath, "klar", "__init__.py"))) {
        root = folder.uri.fsPath;
        break;
      }
    }
  }
  const env = Object.assign({}, process.env);
  if (root) {
    env.PYTHONPATH = root + (env.PYTHONPATH ? path.delimiter + env.PYTHONPATH : "");
  }
  const klarc = cfg.get("klarcPath") || "";
  if (klarc && root) {
    env.KLAR_LIB = path.join(root, "klar");
  }
  // the command that runs a Klar tool: klarc (the compiler written in Klar) or the Python package
  const tool = klarc ? { command: klarc, prefix: [] } : { command: python, prefix: ["-m", "klar"] };
  return { python, env, tool };
}

function startClient(context) {
  const { env, tool } = settings();
  const run = { command: tool.command, args: tool.prefix.concat(["lsp"]), transport: TransportKind.stdio, options: { env } };
  client = new LanguageClient(
    "klar",
    "Klar language server",
    { run, debug: run },
    {
      documentSelector: [{ scheme: "file", language: "klar" }, { scheme: "untitled", language: "klar" }],
      synchronize: { fileEvents: vscode.workspace.createFileSystemWatcher("**/*.klar") },
    }
  );
  client.start().catch((err) => {
    vscode.window.showErrorMessage(
      `Klar: could not start the language server with "${[tool.command].concat(tool.prefix).join(" ")} lsp" ` +
        `(${err.message}). Set "klar.klarcPath" (klarc, no Python needed) or "klar.pythonPath" and, if Klar is not ` +
        `installed with pip, "klar.compilerPath".`
    );
  });
  context.subscriptions.push(client);
}

function runInTerminal(args) {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "klar") {
    vscode.window.showWarningMessage("Klar: open a .klar file first");
    return;
  }
  editor.document.save().then(() => {
    const { env, tool } = settings();
    const term = vscode.window.createTerminal({ name: "Klar", env });
    term.show();
    const file = JSON.stringify(editor.document.uri.fsPath);
    term.sendText(`${[JSON.stringify(tool.command)].concat(tool.prefix).join(" ")} ${args} ${file}`);
  });
}

function activate(context) {
  startClient(context);
  context.subscriptions.push(
    vscode.commands.registerCommand("klar.restartServer", async () => {
      if (client) {
        await client.stop();
      }
      startClient(context);
    }),
    vscode.commands.registerCommand("klar.run", () => runInTerminal("run")),
    vscode.commands.registerCommand("klar.test", () => runInTerminal("test")),
    vscode.commands.registerCommand("klar.view", () => runInTerminal("view --run --open"))
  );
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
