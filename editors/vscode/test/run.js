// End-to-end test: downloads VS Code, loads this extension, opens test/fixture/main.klar and checks the
// language server answers (diagnostics, hover, definition, completion, references, symbols, quick fix).
//   npm install && npm run test:e2e        (Linux needs a display: xvfb-run -a npm run test:e2e)
const fs = require("fs");
const os = require("os");
const path = require("path");
const { runTests } = require("@vscode/test-electron");

(async () => {
  const repo = process.env.KLAR_REPO || path.resolve(__dirname, "..", "..", "..");
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "klar-e2e-"));
  for (const f of fs.readdirSync(path.join(__dirname, "fixture"))) {
    fs.copyFileSync(path.join(__dirname, "fixture", f), path.join(work, f));
  }
  fs.mkdirSync(path.join(work, ".vscode"));
  fs.writeFileSync(path.join(work, ".vscode", "settings.json"), JSON.stringify({ "klar.compilerPath": repo }));
  const out = path.join(work, "result.txt");
  try {
    await runTests({
      extensionDevelopmentPath: path.resolve(__dirname, ".."),
      extensionTestsPath: path.resolve(__dirname, "suite.js"),
      launchArgs: [work, "--disable-extensions", "--no-sandbox", "--disable-gpu"],
      extensionTestsEnv: Object.assign({}, process.env, { KLAR_E2E_FILE: path.join(work, "main.klar"), KLAR_E2E_OUT: out }),
    });
  } catch (e) {
    console.error("VS Code run failed:", e);
    process.exit(1);
  }
  const result = fs.readFileSync(out, "utf8");
  console.log(result);
  process.exit(result.includes("FAIL") ? 1 : 0);
})();
