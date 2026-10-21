// Klar for VS Code: starts the Klar language server (`python -m klar lsp`) and adds a few commands.
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
  return { python, env };
}

function startClient(context) {
  const { python, env } = settings();
  const run = { command: python, args: ["-m", "klar", "lsp"], transport: TransportKind.stdio, options: { env } };
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
      `Klar: could not start the language server with "${python} -m klar lsp" (${err.message}). ` +
        `Set "klar.pythonPath" and, if Klar is not installed with pip, "klar.compilerPath".`
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
    const { python, env } = settings();
    const term = vscode.window.createTerminal({ name: "Klar", env });
    term.show();
    const file = JSON.stringify(editor.document.uri.fsPath);
    term.sendText(`${python} -m klar ${args} ${file}`);
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
