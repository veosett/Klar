# Klar

**Klar** — язык программирования, спроектированный так, чтобы его было удобно **писать, читать и проверять языковой модели**,
и при этом **быстрый**: у него собственный компилятор в машинный код x86-64 и собственный линкер.
Человек в этой схеме — ревьюер: по сигнатуре функции он сразу видит типы, эффекты и контракты.

```klar
use std.math.{gcd}

/// Списывает деньги со счёта
/// >>> assert withdraw(Account { id: 1, balance: 100 }, 30) == Ok(Account { id: 1, balance: 70 })
fn withdraw(acc: Account, amount: Int) -> Result[Account, BankError]
  ensures result.is_err() or amount > 0
{
  if acc.balance < amount {
    return Err(BankError.InsufficientFunds(need: amount, have: acc.balance))
  }
  return Ok(acc with { balance: acc.balance - amount })
}

property "balance never goes negative" (start: Int, amount: Int) {
  match withdraw(Account { id: 1, balance: start.abs() }, amount) {
    Ok(acc) => { assert acc.balance >= 0 },
    Err(_) => { },
  }
}
```

## Быстрый старт

Для компилятора нужен Python 3.8+ (без зависимостей) — это временный bootstrap, см. «Автономность».
Скомпилированные программы не зависят ни от чего.

```bat
klar.bat run examples\features.klar            :: компиляция в машинный код (с кэшем) и запуск
klar.bat build examples\shapes.klar            :: shapes.exe — один файл без зависимостей
klar.bat build app.klar --target linux         :: кросс-компиляция: ELF для Linux из Windows
klar.bat dev examples\bank.klar --json         :: один шаг цикла ИИ: проверка + тесты + запуск
klar.bat test examples\bank.klar               :: test-, doc- и property-тесты
klar.bat fix examples\mistakes.klar            :: применить все безопасные исправления
klar.bat check examples\mistakes.klar --json   :: диагностики в JSON для агента
klar.bat profile bench\programs\primes\primes.klar   :: профилировщик
klar.bat spec                                  :: справка по языку для промпта (~2 тыс. токенов)
klar.bat explain E0405
python bench\run_bench.py                      :: сравнение скорости с C/Rust/Go/Java/JS/Python
python -m unittest discover -s tests           :: тесты компилятора
python tests\native_diff.py                    :: native-бэкенд против эталонного интерпретатора
python bench\ai\run_ai_bench.py                :: когда язык ловит типичные ошибки ИИ (Klar vs 7 языков)
```
На Linux: `sh klar.sh run examples/hello.klar` или `python3 -m klar ...` из корня проекта.

## Как ИИ работает с Klar

1. В системный промпт кладётся вывод `klar spec`: весь язык и вся стандартная библиотека с сигнатурами.
2. Модель пишет код вместе с тестами: `test`, doc-тесты `/// >>>`, `property` и контракты `requires`/`ensures`.
3. Цикл: `klar dev file.klar --json` → JSON с ошибками (код, место, `hint`, `fix`), провалившимися тестами
   (обе стороны `assert`, значения, стек, минимальный контрпример) и полем `next` — что делать дальше.
   `klar fix` применяет безопасные правки сам. Когда всё зелёное — `klar run` / `klar build`.

## Безопасность: ошибки — на этапе компиляции

Как в Rust, всё, что можно отсечь до запуска, отсекает компилятор — с точным местом, подсказкой и часто готовой правкой:

* нет `null`, исключений, индексации `xs[i]`, переполнений, общей изменяемой памяти — этих ошибок просто не написать;
* `Option`/`Result` нельзя использовать как значение, не обработав (`match`, `?`, `unwrap_or`); выброшенный `Result` — ошибка;
* полнота `match`, запрет затенения, обязательные именованные аргументы при ≥3 параметрах, выброшенный результат
  `trim()`/`push()` — ошибка;
* **деление `Int` компилируется, только если делитель доказуемо не ноль** (`if b != 0`, `requires b != 0`, `match`,
  `if xs.is_empty() { return ... }`, переменная, которая только растёт от положительного значения) — E0701;
* рекурсия без базового случая (E0702), вызов с константами, нарушающими `requires` (E0703), заведомо неверный
  аргумент встроенной функции (E0704), индекс `xs.get(xs.len())` (E0705), сортировка неупорядочиваемых значений (E0215).

**Бенчмарк для ИИ** (`bench/ai/`): 13 типичных ошибок моделей, одинаково написанных на 7 языках. Klar останавливает
до запуска **13 из 13**, Rust — 4 (+3 предупреждения), TypeScript strict — 4, Python + mypy — 6 из 12, Go — 4, C++ — 2.
«Молча неверный результат»: Klar — 0, TypeScript и C++ — 8, Go — 6. Подсказку с исправлением дают все сообщения Klar
и половина сообщений Rust; остальные языки — ни одного. Подробно — `bench/ai/README.md`.

## Автономность

Klar не транслируется в C и не использует чужой компилятор или рантайм:

* **компилятор** (`klar/native/`): AST → промежуточное представление KIR → оптимизатор → регистровый аллокатор →
  собственный ассемблер x86-64 → собственный линкер, который пишет ELF (Linux) или PE (Windows);
* **рантайм** (`klar/rt/*.klar`, ~4,5 тыс. строк) написан **на самом Klar** (системное подмножество с типом `Word`):
  аллокатор, подсчёт ссылок, большие целые, печать Float, строки UTF-8, List, Map, ввод-вывод;
* исполняемый файл обращается только к ядру ОС: системные вызовы на Linux, `KERNEL32.dll` на Windows. Ни libc, ни Python;
* Python сейчас нужен только как bootstrap для самого компилятора. Следующий этап — переписать компилятор на Klar
  (self-hosting, план в `docs/ARCHITECTURE.md`, раздел 6).

## Скорость

Время вычислений, мс (лучшее из 5; Intel Core i5-8400, Linux, 2 vCPU; меньше — лучше):

| задача | C -O2 | **Klar** | Java 21 | Node.js 22 | Python 3.10 |
|---|---:|---:|---:|---:|---:|
| fib(25), рекурсия | 0,16 | **1,1** | 0,65 | 2,3 | 18,6 |
| loop, 300 тыс. итераций с `%` | 0,98 | **1,3** | 5,0 | 6,4 | 41,6 |
| primes, перебор делителей до 30 000 | 1,9 | **3,6** | 4,9 | 2,9 | 23,9 |
| mandelbrot, Float | 0,38 | **1,1** | 3,7 | 5,2 | 21,9 |
| collections, map/filter/sort 200 тыс. | 5,1 | **10,0** | 37,7 | 43,1 | 39,3 |
| strings, 100 тыс. строк, join/split | 11,6 | **19,9** | 72,7 | 36,3 | 28,5 |

Klar в 1,4–32 раза быстрее Python, на 4 задачах из 6 быстрее Java и Node.js и в 1,3–7 раз медленнее C — при этом
`Int` никогда не переполняется, все значения неизменяемы, а ошибки показывают стек вызовов Klar. Исполняемый файл
стартует за 1–2 мс. Методика, все 9 реализаций (C, Rust, Go, Java, JS, Python и три бэкенда Klar) и история
оптимизаций — в `bench/README.md`.

## Что внутри

| Часть | Что делает |
|---|---|
| Язык | статические типы с выводом, дженерики (функции, записи, enum), алиасы, константы, `Option`/`Result`/`?`, `match` с guard'ами и проверкой полноты, лямбды, UFCS, модули `use m.{a, b}`, эффекты `uses io`, контракты |
| Проверка | ~60 кодов диагностик с подсказками и машинными `fix`, распознавание «чужих» идиом (`.length`, `&&`, `unwrap`, `xs[0]`, `null`…) |
| Бэкенды | **native** (по умолчанию): x86-64 Linux/Windows; `--py`: байткод Python; `--interp`: эталонный интерпретатор. Дифференциальные тесты держат их идентичными |
| Тесты | `test`, doc-тесты, property-тесты со сжатием контрпримера, `assert` с обеими сторонами |
| Инструменты | `dev`, `fix`, `profile`, `build`, `spec`, `explain`, `ast`, `--json` везде |
| Stdlib | ~110 встроенных функций и методов + модули на Klar `std.math`, `std.text`, `std.list`, `std.result`; каждая функция покрыта тестом |
| Бенчмарки | 6 задач × 9 реализаций, сверка результатов |

## Структура

```
docs/ARCHITECTURE.md   архитектура: принципы, тулчейн, нативный компилятор, self-hosting, дорожная карта
docs/FEATURES.md       анализ основных языков → список функций Klar со статусами
docs/SPEC.md           спецификация: грамматика, типы, семантика
klar/                  фронтенд (lexer, parser, checker, loader), интерпретатор, codegen (Python), cli
klar/native/           компилятор в машинный код: lower, kir, opt, regalloc, emit, x64, link, build
klar/rt/*.klar         рантайм native-бэкенда на самом Klar
klar/prelude.klar      прелюдия на Klar (Pair, Entry, Indexed, PI, E)
klar/std/*.klar        стандартные модули на Klar с тестами
klar/ai_reference.md   компактная справка для модели (klar spec)
examples/              hello, bank, collections, shapes, features (+ lib/geo), mistakes
tests/                 тесты компилятора, tests/stdlib, tests/native, native_diff.py
bench/                 скорость: программы на 8 языках (C, C++, Rust, Go, Java, JS, Python, Klar), run_bench.py
bench/ai/              «насколько ИИ проще»: 13 типичных ошибок × 7 языков, run_ai_bench.py
```
