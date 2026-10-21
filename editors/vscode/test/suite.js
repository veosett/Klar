const vscode = require("vscode");
const fs = require("fs");
const path = require("path");

exports.run = async function () {
  const lines = [];
  const check = (name, ok, got) => lines.push(`${ok ? "PASS" : "FAIL"} ${name}: ${JSON.stringify(got)}`);
  try {
    const doc = await vscode.workspace.openTextDocument(process.env.KLAR_E2E_FILE);
    await vscode.window.showTextDocument(doc);
    let diags = [];
    for (let i = 0; i < 150 && diags.length === 0; i++) {
      await new Promise((r) => setTimeout(r, 200));
      diags = vscode.languages.getDiagnostics(doc.uri);
    }
    const codes = diags.map((d) => String(d.code && d.code.value !== undefined ? d.code.value : d.code));
    check("diagnostics", ["E0606", "W0402", "E0202"].every((c) => codes.includes(c)), codes);
    const at = (l, c) => new vscode.Position(l, c);
    const hover = await vscode.commands.executeCommand("vscode.executeHoverProvider", doc.uri, at(10, 9));
    const htext = hover.map((h) => h.contents.map((c) => c.value || c).join("")).join("");
    check("hover", htext.includes("fn total[T: Shape]") && htext.includes("Sum of areas"), htext);
    const def = await vscode.commands.executeCommand("vscode.executeDefinitionProvider", doc.uri, at(8, 11));
    const dtext = def.map((d) => `${path.basename((d.uri || d.targetUri).fsPath)}:${(d.range || d.targetRange).start.line}`);
    check("definition", dtext.includes("geo.klar:13"), dtext);
    const comp = await vscode.commands.executeCommand("vscode.executeCompletionItemProvider", doc.uri, at(11, 14), ".");
    const labels = comp.items.map((i) => (typeof i.label === "string" ? i.label : i.label.label));
    check("completion", labels.includes("len") && labels.includes("map"), labels.slice(0, 8));
    const refs = await vscode.commands.executeCommand("vscode.executeReferenceProvider", doc.uri, at(4, 28));
    check("references", refs.length === 3, refs.map((r) => `${path.basename(r.uri.fsPath)}:${r.range.start.line}`));
    const syms = await vscode.commands.executeCommand("vscode.executeDocumentSymbolProvider", doc.uri);
    check("symbols", syms.map((s) => s.name).join() === "total,main", syms.map((s) => s.name));
    const e0606 = diags.find((d) => String(d.code && d.code.value !== undefined ? d.code.value : d.code) === "E0606");
    const actions = await vscode.commands.executeCommand("vscode.executeCodeActionProvider", doc.uri, e0606.range);
    const titles = actions.map((a) => a.title);
    check("quick fix", titles.some((t) => t.includes("pub")), titles);
  } catch (e) {
    lines.push(`FAIL exception: ${e && e.stack ? e.stack : e}`);
  }
  fs.writeFileSync(process.env.KLAR_E2E_OUT, lines.join("\n") + "\n");
};
