# Klar for Visual Studio Code

Syntax highlighting (including string interpolation and doc-tests), snippets (`fn`, `main`, `test`,
`property`, `match`, `type`, `enum`) and a `$klar` problem matcher for tasks that run `klar check`.

Install from this folder: `code --install-extension <path>` after `npx @vscode/vsce package`, or copy the folder to
`~/.vscode/extensions/klar-lang`. Example task (`.vscode/tasks.json`):

```json
{ "version": "2.0.0", "tasks": [{ "label": "klar check", "type": "shell",
  "command": "python -m klar check ${file}", "problemMatcher": "$klar", "group": "build" }] }
```
