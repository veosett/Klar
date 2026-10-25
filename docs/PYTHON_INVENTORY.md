# Python в репозитории — инвентарь

Сгенерировано `tools/inventory.klar` из первоисточников: `git ls-files`, граф импортов Python-модулей (достижимость от `klar/cli.py`), пары с Klar-файлами и `git log`. Не править руками — перезапустить:

```
klarc run tools/inventory.klar -- --coverage cov.json
```

## Итог по ролям

| Роль | Файлов | Строк |
|---|---|---|
| Python-бэкенд (`--py`, `--interp`) | 3 | 1916 |
| заблокирован | 1 | 525 |
| маркер пакета | 3 | 3 |
| программа бенчмарка | 42 | 412 |
| тестовая обвязка | 5 | 4383 |
| эталон (оракул) | 40 | 19779 |

## Цена двойной поддержки

- Коммитов в истории: 51; из них меняют и `klar/*.py`, и `compiler/*.klar`: 23 (45%).
- Изменения модулей-оракулов вместе с их парой на Klar: 84 из 196 (43%).
  Каждое такое изменение — одна и та же правка, сделанная дважды. Коммиты в истории крупные, поэтому это грубая оценка.

## Каждый файл

«Вместе» — коммиты, менявшие файл вместе с его парой на Klar, из всех коммитов, менявших файл. «Покрытие» — доля операторов, которые выполняет набор тестов (coverage.py, если передан `--coverage`).

| Файл | Строк | Роль | Пара на Klar | Вместе | Покрытие |
|---|---|---|---|---|---|
| `bench/ai/cases/01_missing_key/prog.py` | 6 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/02_parse_error/prog.py` | 6 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/03_divide_by_zero/prog.py` | 5 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/04_discarded_update/prog.py` | 3 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/05_missing_case/prog.py` | 30 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/06_argument_order/prog.py` | 5 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/07_integer_overflow/prog.py` | 8 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/08_off_by_one/prog.py` | 2 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/10_foreign_method/prog.py` | 2 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/11_string_plus_number/prog.py` | 2 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/12_no_base_case/prog.py` | 5 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/cases/13_sort_records/prog.py` | 12 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/llm_bench.py` | 525 | заблокирован: нужна сеть (ROADMAP 10) | — | 0/1 | — |
| `bench/ai/tasks/ref/python/01_word_freq.py` | 6 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/02_average.py` | 4 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/03_rle.py` | 10 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/04_balanced.py` | 10 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/05_fizzbuzz.py` | 5 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/06_top_k.py` | 5 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/07_transpose.py` | 4 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/08_roman.py` | 10 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/09_search.py` | 11 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/10_intervals.py` | 8 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/11_bank.py` | 14 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/12_caesar.py` | 10 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/13_prefix.py` | 8 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/14_anagrams.py` | 5 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/15_csv.py` | 25 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/16_primes.py` | 10 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/17_safe_div.py` | 8 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/18_islands.py` | 18 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/19_snake.py` | 8 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/20_fib_mod.py` | 5 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/21_dedupe.py` | 8 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/22_histogram.py` | 2 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/23_email.py` | 6 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/ai/tasks/ref/python/24_eval_rpn.py` | 26 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/programs/collections/collections.py` | 12 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/programs/fib/fib.py` | 14 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/programs/loop/loop.py` | 14 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/programs/mandelbrot/mandelbrot.py` | 23 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/programs/primes/primes.py` | 24 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `bench/programs/strings/strings.py` | 13 | программа бенчмарка: Python — один из сравниваемых языков | — | 0/1 | — |
| `klar/__init__.py` | 2 | маркер пакета | — | 0/6 | 100% |
| `klar/__main__.py` | 5 | эталон (оракул): есть пара на Klar | `compiler/klarc.klar` | 0/1 | 100% |
| `klar/builtins.py` | 1211 | эталон (оракул): есть пара на Klar | `compiler/builtin_sigs.klar`, `klar/rt/str.klar`, `klar/rt/list.klar` | 13/14 | 94% |
| `klar/checker.py` | 2262 | эталон (оракул): есть пара на Klar | `compiler/checker.klar` | 11/16 | 86% |
| `klar/cli.py` | 730 | эталон (оракул): есть пара на Klar | `compiler/klarc.klar` | 4/12 | 73% |
| `klar/codegen.py` | 1017 | Python-бэкенд (`--py`, `--interp`): его место занимает native | — | 0/4 | 85% |
| `klar/contracts.py` | 60 | эталон (оракул): есть пара на Klar | `compiler/contracts.klar` | 1/1 | 91% |
| `klar/diagnostics.py` | 283 | эталон (оракул): есть пара на Klar | `compiler/report.klar`, `compiler/similar.klar` | 0/14 | 91% |
| `klar/errors.py` | 43 | эталон (оракул): есть пара на Klar | `compiler/report.klar` | 0/2 | 94% |
| `klar/fakes.py` | 122 | эталон (оракул): есть пара на Klar | `klar/rt/fake.klar` | 1/1 | 72% |
| `klar/interpreter.py` | 734 | Python-бэкенд (`--py`, `--interp`): его место занимает native | — | 0/6 | 90% |
| `klar/lexer.py` | 287 | эталон (оракул): есть пара на Klar | `compiler/lexer.klar` | 0/5 | 94% |
| `klar/loader.py` | 352 | эталон (оракул): есть пара на Klar | `compiler/loader.klar` | 1/5 | 92% |
| `klar/native/__init__.py` | 0 | маркер пакета | — | 0/1 | — |
| `klar/native/a64.py` | 273 | эталон (оракул): есть пара на Klar | `compiler/a64.klar` | 0/1 | 94% |
| `klar/native/build.py` | 102 | эталон (оракул): есть пара на Klar | `compiler/klarc.klar` | 2/5 | 84% |
| `klar/native/emit.py` | 1983 | эталон (оракул): есть пара на Klar | `compiler/emit.klar` | 8/12 | 96% |
| `klar/native/emit_a64.py` | 1196 | эталон (оракул): есть пара на Klar | `compiler/emit_a64.klar` | 6/7 | 93% |
| `klar/native/intrinsics.py` | 85 | эталон (оракул): есть пара на Klar | `compiler/lower.klar` | 4/10 | 100% |
| `klar/native/kir.py` | 48 | эталон (оракул): есть пара на Klar | `compiler/lower.klar` | 0/1 | 100% |
| `klar/native/link.py` | 219 | эталон (оракул): есть пара на Klar | `compiler/link.klar` | 1/3 | 99% |
| `klar/native/lower.py` | 1883 | эталон (оракул): есть пара на Klar | `compiler/lower.klar` | 8/13 | 94% |
| `klar/native/opt.py` | 498 | эталон (оракул): есть пара на Klar | `compiler/opt.klar` | 0/2 | 96% |
| `klar/native/own.py` | 445 | эталон (оракул): есть пара на Klar | `compiler/own.klar` | 1/1 | 98% |
| `klar/native/regalloc.py` | 276 | эталон (оракул): есть пара на Klar | `compiler/regalloc.klar` | 2/5 | 96% |
| `klar/native/x64.py` | 379 | эталон (оракул): есть пара на Klar | `compiler/x64.klar` | 0/2 | 94% |
| `klar/nodes.py` | 435 | эталон (оракул): есть пара на Klar | `compiler/ast.klar`, `compiler/astjson.klar` | 5/10 | 95% |
| `klar/packages.py` | 265 | эталон (оракул): есть пара на Klar | `compiler/pkg.klar`, `compiler/manifest.klar` | 1/1 | 71% |
| `klar/parser.py` | 1123 | эталон (оракул): есть пара на Klar | `compiler/parser.klar` | 5/10 | 93% |
| `klar/safety.py` | 944 | эталон (оракул): есть пара на Klar | `compiler/safety.klar` | 1/4 | 93% |
| `klar/sandbox.py` | 102 | эталон (оракул): есть пара на Klar | `klar/rt/sandbox.klar` | 1/1 | 93% |
| `klar/tools/__init__.py` | 1 | маркер пакета | — | 0/1 | — |
| `klar/tools/commands.py` | 305 | эталон (оракул): есть пара на Klar | `compiler/commands.klar` | 1/7 | 53% |
| `klar/tools/context.py` | 197 | эталон (оракул): есть пара на Klar | `compiler/context.klar` | 1/1 | 97% |
| `klar/tools/fmt.py` | 219 | эталон (оракул): есть пара на Klar | `compiler/fmt.klar` | 0/4 | 95% |
| `klar/tools/inspect.py` | 380 | эталон (оракул): есть пара на Klar | `compiler/inspect.klar` | 0/5 | 85% |
| `klar/tools/lsp.py` | 936 | эталон (оракул): есть пара на Klar | `compiler/lsp.klar` | 1/3 | 65% |
| `klar/tools/mcp.py` | 201 | эталон (оракул): есть пара на Klar | `compiler/mcp.klar` | 2/2 | 86% |
| `klar/tools/patch.py` | 313 | эталон (оракул): есть пара на Klar | `compiler/patch.klar` | 0/2 | 76% |
| `klar/tools/pkg.py` | 372 | эталон (оракул): есть пара на Klar | `compiler/pkg.klar` | 1/2 | 83% |
| `klar/tools/repl.py` | 323 | эталон (оракул): есть пара на Klar | `compiler/repl.klar` | 0/1 | 78% |
| `klar/tools/runtools.py` | 213 | эталон (оракул): есть пара на Klar | `compiler/dev.klar`, `compiler/profile.klar`, `compiler/coverage.klar`, `compiler/evaluate.klar` | 1/4 | 79% |
| `klar/tools/view.py` | 336 | эталон (оракул): есть пара на Klar | `compiler/view.klar` | 0/3 | 65% |
| `klar/trace.py` | 134 | эталон (оракул): есть пара на Klar | `compiler/trace.klar`, `klar/rt/trace.klar` | 0/1 | 90% |
| `klar/types.py` | 239 | эталон (оракул): есть пара на Klar | `compiler/types.klar` | 1/2 | 90% |
| `klar/values.py` | 165 | Python-бэкенд (`--py`, `--interp`): его место занимает native | — | 0/2 | 92% |
| `tests/bootstrap.py` | 193 | тестовая обвязка: сверяет Python и Klar | — | 0/7 | — |
| `tests/macho_run.py` | 279 | тестовая обвязка: сверяет Python и Klar | — | 0/1 | — |
| `tests/native_diff.py` | 145 | тестовая обвязка: сверяет Python и Klar | — | 0/13 | — |
| `tests/selfhost.py` | 1328 | тестовая обвязка: сверяет Python и Klar | — | 0/17 | — |
| `tests/test_klar.py` | 2438 | тестовая обвязка: сверяет Python и Klar | — | 0/33 | — |
