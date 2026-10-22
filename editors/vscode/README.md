# Klar for Visual Studio Code

* **Language server** (`klar lsp`): errors and warnings as you type with quick fixes, hover (types, signatures,
  docs), go to definition, find references, rename, completion (names and `.` members), signature help,
  outline, formatting.
* Syntax highlighting (string interpolation, doc-tests), snippets (`fn`, `main`, `test`, `property`, `match`,
  `type`, `enum`, `trait`, `impl`).
* Commands: **Klar: Run current file**, **Klar: Test current file**, **Klar: Show how the program works**
  (`klar view`), **Klar: Restart language server**.

## Install

```sh
cd editors/vscode
npm install
npx @vscode/vsce package          # -> klar-lang-0.7.0.vsix
code --install-extension klar-lang-0.7.0.vsix
```

The extension runs `python3 -m klar lsp` (`python` on Windows). If Klar is not installed with pip, set
**klar.compilerPath** to the folder of your Klar checkout (the one that contains `klar/`); a workspace that *is*
a Klar checkout is detected automatically. **klar.pythonPath** selects the Python interpreter.

## Test

`npm run test:e2e` downloads VS Code, loads the extension, opens `test/fixture/main.klar` and checks the answers
of the language server (on Linux without a display: `xvfb-run -a npm run test:e2e`).
