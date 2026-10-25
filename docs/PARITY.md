# `klar` и `klarc` — сравнение команд и флагов

Сгенерировано `tools/parity.klar` из самих инструментов: `klar --help`, `klar <команда> --help`, текст usage `klarc` и строковые литералы `compiler/*.klar`. Не править руками — перезапустить:

```
klarc run tools/parity.klar -- --klarc build/klarc
```

## Итог

- Команд у `klar`: 30; есть в `klarc`: 30 (из них не названы в usage: 0).
- Флагов (без флагов Python-бэкендов): 80; есть в `klarc`: 80.

## По командам

«Нет в klarc» — флаг `klar`, которого нет ни в usage `klarc`, ни среди литералов его исходников. «Только в klarc» — флаги из usage `klarc`, которых нет у `klar`. «Python» — флаги Python-бэкендов, не нужные native-компилятору.

| Команда | В klarc | Флагов у klar | Нет в klarc | Только в klarc | Python |
|---|---|---|---|---|---|
| `replay` | ✅ | 3 | — | `--lib` | `--interp` |
| `run` | ✅ | 8 | — | `--lib` | `--interp`, `--py`, `--verbose`, `--emit-python` |
| `build` | ✅ | 5 | — | `--lib` | — |
| `check` | ✅ | 1 | — | `--lib` | — |
| `test` | ✅ | 5 | — | `--lib` | — |
| `profile` | ✅ | 3 | — | — | — |
| `dev` | ✅ | 7 | — | — | — |
| `fix` | ✅ | 4 | — | `--lib` | — |
| `ast` | ✅ | 1 | — | — | — |
| `spec` | ✅ | 0 | — | — | — |
| `explain` | ✅ | 0 | — | — | — |
| `fmt` | ✅ | 3 | — | — | — |
| `outline` | ✅ | 2 | — | — | — |
| `doc` | ✅ | 3 | — | — | — |
| `refs` | ✅ | 1 | — | — | — |
| `context` | ✅ | 2 | — | — | — |
| `rename` | ✅ | 2 | — | — | — |
| `eval` | ✅ | 3 | — | — | — |
| `coverage` | ✅ | 4 | — | — | — |
| `view` | ✅ | 5 | — | — | — |
| `new` | ✅ | 1 | — | — | — |
| `patch` | ✅ | 4 | — | — | — |
| `add` | ✅ | 8 | — | — | — |
| `remove` | ✅ | 2 | — | — | — |
| `fetch` | ✅ | 2 | — | — | — |
| `update` | ✅ | 2 | — | — | — |
| `deps` | ✅ | 2 | — | — | — |
| `lsp` | ✅ | 1 | — | — | — |
| `repl` | ✅ | 0 | — | `--plain` | — |
| `mcp` | ✅ | 1 | — | `--klarc` | — |
