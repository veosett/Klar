# Klar за 20 минут — руководство в картинках

Это руководство для людей: что за язык, как на нём писать и читать, почему он устроен именно так.
Справочник для моделей — `klar spec`, полная грамматика — [SPEC.md](SPEC.md), устройство компилятора — [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Идея: ИИ пишет, компилятор проверяет, человек читает

```mermaid
flowchart LR
    ai["🤖 ИИ пишет код<br/>и тесты рядом с ним"] --> klar["⚙️ Компилятор Klar<br/>типы · эффекты · полнота<br/>безопасность"]
    klar -- "ошибка + подсказка + правка" --> ai
    klar -- "всё проверено" --> exe["📦 Быстрый исполняемый файл<br/>Linux / Windows / macOS"]
    klar --> view["👀 klar view<br/>схема программы для человека"]
    view --> human["🧑 Человек-ревьюер"]
```

Klar убирает целые классы ошибок ещё до запуска. Модель исправляет их по точным подсказкам,
а человек смотрит на результат, а не ищет баги.

## 2. Первая программа

```klar
/// Приветствие: запустите `klar run hello.klar`.
fn main() uses io {
  let name = "мир"
  print("Привет, {name}!")
}
```

* `fn main() uses io` — точка входа. `uses io` объявляет, что функция печатает (подробнее — раздел 9).
* `let` — значение, которое нельзя изменить. `"…{name}…"` — подстановка значения в строку.
* Нет `;`: одна инструкция на строку. Блоки — в `{ }`.

```sh
klar run hello.klar      # скомпилировать в машинный код и запустить
klar build hello.klar    # получить hello / hello.exe — один файл без зависимостей
```

## 3. Типы данных

```mermaid
flowchart TB
    T["Типы Klar"] --> P["Простые"]
    T --> C["Коллекции"]
    T --> M["«Может не быть / может не получиться»"]
    T --> U["Свои"]
    P --> P1["Int — целое любой длины"]
    P --> P2["Float — дробное"]
    P --> P3["Bool — true / false"]
    P --> P4["Str — строка Unicode"]
    P --> P5["Bytes — байты (файлы, протоколы)"]
    C --> C1["List[T] — список"]
    C --> C2["Map[K, V] — словарь (порядок вставки)"]
    M --> M1["Option[T] — Some(v) или None"]
    M --> M2["Result[T, E] — Ok(v) или Err(e)"]
    U --> U1["type — запись с полями"]
    U --> U2["enum — один из вариантов"]
    U --> U3["type X = new T — отдельный тип над T"]
```

```klar
type Point { x: Float, y: Float }                       // запись

enum Shape {                                            // варианты
  Circle(radius: Float),
  Rect(w: Float, h: Float),
}

fn main() uses io {
  let p = Point { x: 1.0, y: 2.0 }
  let _shape = Shape.Circle(radius: 2.0)                // `_` в начале имени: «пока не используется»
  let big = 2.pow(100)                                  // Int не переполняется
  print("{p.x} {big}")
}
```

Когда у числа есть смысл, дайте ему свой тип — **newtype**. Метры не сложатся с секундами, а процент не выйдет за
границы: строки `requires` проверяет конструктор, и другого способа получить значение нет.

```klar
type Meters = new Float

type Percent = new Int
  requires value >= 0 and value <= 100

fn main() uses io {
  let d = Meters(2.5)                                   // построить: Meters(x); прочитать: d.value
  let p = Percent(42)                                   // Percent(150) — ошибка компиляции E0703
  print("{d.value} m, {p.value}%")
}
```

**Нет `null` и нет исключений.** Если значения может не быть, это видно по типу (`Option`). Если операция
может не удаться, это тоже видно по типу (`Result`). Компилятор не даст забыть оба случая.

## 4. Неизменяемость: значения не меняются, меняются имена

```mermaid
flowchart LR
    a["xs = [1, 2, 3]"] -- "xs.push(4)" --> b["НОВЫЙ список [1, 2, 3, 4]"]
    a -. "xs не изменился" .-> a
    b -- "xs = xs.push(4)" --> c["теперь имя xs<br/>указывает на новый список"]
```

```klar
fn main() uses io {
  var xs = [1, 2, 3]       // var — имя можно перепривязать
  xs = xs.push(4)          // правильно: сохранили новый список
  let ys = xs.push(5)      // ys = [1, 2, 3, 4, 5], xs = [1, 2, 3, 4]
  print("{xs} {ys}")
}
```

Строка `xs.push(4)` без присваивания — **ошибка компиляции** E0405: это самая частая ошибка моделей.
Неизменяемость делает код предсказуемым: если значение передано в функцию, ничего «само» не поменяется.
Скорости это не мешает: если на список ссылается только одно имя, компилятор незаметно меняет его на месте — в
том числе когда состояние передаётся через функции (`s = add(s, x)`, `return s with { items: s.items.push(x) }`).

## 5. Функции: сигнатура — это договор

```mermaid
flowchart LR
    in["Аргументы<br/>(типы обязательны)"] --> req{"requires<br/>предусловие"}
    req -- "ложно" --> e1["ошибка вызывающего<br/>R0002"]
    req -- "истинно" --> body["Тело функции"]
    body --> ens{"ensures<br/>постусловие"}
    ens -- "ложно" --> e2["ошибка в теле<br/>R0003"]
    ens -- "истинно" --> out["Результат<br/>(тип обязателен)"]
```

```klar
/// Делит сумму поровну.
/// >>> assert share(total: 10, people: 3, min: 1) == 3
fn share(total: Int, people: Int, min: Int) -> Int
  requires people > 0
  ensures result >= 0 or total < 0
{
  let part = total / people
  return part.max(min)
}

fn main() uses io {
  print(share(total: 100, people: 4, min: 1))
}
```

* Типы параметров и результата всегда записаны: функцию можно понять по одной строке.
* Если у функции 3 параметра и больше, а аргументы одного типа можно незаметно перепутать, при вызове нужно писать
  имена: `share(total: 100, people: 4, min: 1)`. Если аргументы перепутать нельзя, имена не нужны. Это так, когда
  у параметров разные типы или когда каждый аргумент назван как свой параметр: `cell(grid, r, c)`,
  `cell(grid, nr, c - 1)`.
* `/// >>>` — пример в документации, который `klar test` запускает как тест.
* `total / people` компилируется только потому, что `requires people > 0` доказывает: делитель не ноль (раздел 11).

## 6. Option, Result и `?`

```mermaid
flowchart TB
    get["users.get(id)"] --> o{"Option"}
    o -- "Some(user)" --> use["используем user"]
    o -- "None" --> none["нет пользователя:<br/>обрабатываем явно"]
    parse["text.to_int()"] --> r{"Option[Int]"}
    r -- "Some(n)" --> ok["работаем с n"]
    r -- "None" --> q["оператор ? — сразу вернуть None<br/>из текущей функции"]
```

```klar
fn age_next_year(ages: Map[Str, Int], name: Str) -> Option[Int] {
  let age = ages.get(name)?          // None → функция сразу возвращает None
  return Some(age + 1)
}

fn main() uses io {
  let ages = Map { "ann": 31 }
  match age_next_year(ages, "bob") {
    Some(a) => print("будет {a}"),
    None => print("не знаем такого"),
  }
  print(ages.get("ann").unwrap_or(0))   // или значение по умолчанию
}
```

Использовать `Option` как обычное число нельзя: `ages.get(name) + 1` — ошибка компиляции с подсказкой
обработать `None`. Для ошибок с описанием есть `Result[T, E]` и `Err(...)`: функция обязана объявить в типе,
что может не получиться, а вызывающая — обработать это (`match`, `?` или `let _ =` для явного отказа).

## 7. match: компилятор следит, что учтены все случаи

```mermaid
flowchart LR
    s["Shape"] --> c["Circle(radius)"]
    s --> r["Rect(w, h)"]
    s --> t["Triangle(a, h)<br/>добавили позже"]
    t -. "забыли ветку?" .-> err["ошибка E0301:<br/>missing Shape.Triangle(...) =>"]
```

```klar
enum Shape {
  Circle(radius: Float),
  Rect(w: Float, h: Float),
}

fn area(s: Shape) -> Float {
  return match s {
    Shape.Circle(r) => 3.14159 * r * r,
    Shape.Rect(w, h) => w * h,
  }
}

fn label(n: Int) -> Str {
  return match n {
    0 => "ноль",
    x if x < 0 => "отрицательное",     // условие в ветке (guard)
    _ => "положительное",
  }
}

fn main() uses io {
  print("{area(Shape.Rect(w: 2.0, h: 3.0))} {label(-5)}")
}
```

Если в `enum` добавить вариант, компилятор покажет каждый `match`, где он не обработан, вместе с готовым
текстом недостающей ветки. `match` — это ещё и замена тернарного оператора:
`let sign = match n > 0 { true => 1, false => -1 }`.

## 8. Трейты: общее поведение у разных типов

Трейт — это список методов, которые тип обещает иметь. Обобщённая функция с ограничением `[T: Shape]`
принимает любой тип, у которого есть `impl Shape`, и может вызывать эти методы.

```mermaid
flowchart LR
    tr["trait Shape<br/>fn area(self) -> Float<br/>fn label(self) -> Str — по умолчанию"]
    c["impl Shape for Circle"] --> tr
    r["impl Shape for Rect"] --> tr
    tr --> g["fn total[T: Shape](xs: List[T])<br/>вызывает x.area()"]
    g -- "total([круги])" --> c2["в машинном коде:<br/>прямой вызов Circle.area"]
    g -- "total([прямоугольники])" --> r2["прямой вызов Rect.area"]
```

```klar
trait Shape {
  fn area(self) -> Float
  fn label(self) -> Str {               // метод по умолчанию: impl может его не писать
    return "фигура площадью {self.area()}"
  }
}

type Circle { radius: Float }
type Rect { w: Float, h: Float }

impl Shape for Circle {
  fn area(self) -> Float {
    return 3.14159 * self.radius * self.radius
  }
}

impl Shape for Rect {
  fn area(self) -> Float {
    return self.w * self.h
  }
  fn label(self) -> Str {               // свой вариант вместо метода по умолчанию
    return "прямоугольник {self.w}×{self.h}"
  }
}

fn total[T: Shape](xs: List[T]) -> Float {
  return xs.map(fn(s) => s.area()).sum_float()
}

fn main() uses io {
  print(total([Circle { radius: 1.0 }, Circle { radius: 2.0 }]))
  print(Rect { w: 2.0, h: 3.0 }.label())
}
```

Что проверяет компилятор:

| ошибка | когда |
|---|---|
| E0221 | в `impl` нет обязательного метода, лишний метод или сигнатура не совпадает с трейтом (`klar fix` вставит заготовки `todo(...)`) |
| E0220 | `total([точки])`, а `impl Shape for Point` нет; или у параметра `U` нет ограничения `[U: Shape]` |
| E0222 | второй `impl` того же трейта для того же типа или `impl` не в модуле трейта/типа |
| E0224 | трейт использован как тип (`fn f(s: Shape)`) |

Правила простые. Методы трейта всегда принимают `self` первым параметром. `Self` внутри трейта означает «тот тип,
который реализует трейт». `impl` пишут для `Int`, `Float`, `Bool`, `Str`, `Bytes` и для своих `type` и `enum`. Для
обобщённых типов `impl` тоже обобщённый: `impl[T: Show] Show for List[T]` даёт `show()` любому списку, элементы
которого умеют `show()`, а `impl[T] Show for Box[T]` — любому `Box`. Нужен список
разных фигур — объявите `enum` с вариантом на каждую фигуру и реализуйте трейт для него: каждый метод будет одним
`match`.

## 9. Эффекты: по сигнатуре видно, что функция делает с миром

```mermaid
flowchart TB
    main["main() uses io"] --> report["report() uses io<br/>печатает"]
    main --> calc["total(xs) — чистая"]
    report --> fmt["format(x) — чистая"]
    calc --> sum["xs.sum() — чистая"]
    bad["calc2() без uses"] -. "вызывает print" .-> err["ошибка E0401:<br/>добавьте uses io"]
```

| эффект | что разрешает |
|---|---|
| `io` | печать, чтение ввода, `dbg` |
| `fs` | файлы (`read_file`, `write_file`, `list_dir`, `make_dir`, `remove_file` возвращают `Result`; `file_exists`, `is_dir`, `current_dir`) |
| `time` | часы (`now_ms`, `now_ns`) |
| `rand` | случайные числа |
| `proc` | запуск других программ (`run_command`, `run_capture`) |
| `net` | сеть (зарезервировано) |

Функция без `uses` — **чистая**: при одних и тех же аргументах она всегда даёт один и тот же результат.
Её можно тестировать, кэшировать и спокойно вызывать. `klar view` раскрашивает такие функции зелёным.

Эффекты есть и в типах функций, поэтому чистота не теряется через функции-значения:

```klar
fn twice(f: fn(Int) -> Int, x: Int) -> Int {                  // f — чистая
  return f(f(x))
}

fn each_report(xs: List[Int], report: fn(Int) -> Unit uses io) uses io {
  for x in xs {
    report(x)                                                // вызов требует io
  }
}

fn make_logger(prefix: Str) -> (fn(Str) -> Unit uses io) {    // скобки: uses у возвращаемой функции
  return fn(msg) => print("{prefix}: {msg}")
}
```

`twice(print_it, 1)` с `fn print_it(x: Int) -> Int uses io` — ошибка E0202: в `fn(Int) -> Int` нет `uses io`.
Встроенные `map`, `filter`, `fold` и другие делают то, что делает переданная функция: `xs.map(show_item)` требует
`uses io` у вызывающей функции. Полный пример — `examples/effects.klar`.

Те же эффекты работают как права при запуске чужого кода: `klar run --allow fs:./data,time main.klar` разрешает
только файлы в `./data` и часы. Попытка прочитать другой файл или запустить программу (`run_command`) остановится
ошибкой R0016 с именем права, которого не хватило. Печать (`io`) разрешена всегда.

### Параллелизм: `par_map`

Чистота — то, что делает параллельный код безопасным. `xs.par_map(f)` даёт тот же список, что `xs.map(f)`, но в
нативном коде раскладывает элементы по ядрам процессора (рабочие процессы, по непрерывному куску на ядро):

```klar
fn score(doc: Str) -> Int {          // чистая: без `uses`
  return doc.split(" ").filter(fn(w) => w.len() > 3).len()
}

fn main() uses io {
  let docs = ["the quick brown fox", "jumps over the lazy dog", "hello parallel world"]
  let scores = docs.par_map(score)    // все ядра; результат и порядок — как у map
  print(scores.sum())                 // эффекты — потом, в main
}

test "par_map gives the result of map" {
  let docs = ["a bb ccc dddd", "eeeee"]
  assert docs.par_map(score) == docs.map(score)
}
```

Компилятор проверяет то, на чём держится безопасность (ошибки E0406 / E0401):
* `f` — лямбда без эффектов или функция, в типе которой нет `uses`: из другого процесса нельзя ничего напечатать,
  записать в файл или узнать время;
* в результатах нет функций (они пересылаются между процессами).

Нет блокировок, гонок данных и ошибок «иногда»: значения неизменяемы, `f` чистая, поэтому результат не зависит от
того, кто успел первым. Ошибка выполнения внутри `f` сообщается так же, как у `map` (первый упавший элемент). Где
рабочих процессов нет (пока Windows, один процессор, интерпретатор), `par_map` — это просто `map`.

## 10. Тесты — часть языка

```mermaid
flowchart LR
    t1["test &quot;...&quot; { assert ... }"] --> run["klar test"]
    t2["/// >>> пример в документации"] --> run
    t3["property &quot;...&quot; (xs: List[Int])"] --> gen["100 случайных входов"] --> run
    run -- "провал" --> show["обе стороны assert,<br/>значения переменных, стек,<br/>минимальный контрпример"]
```

```klar
fn reverse_twice(xs: List[Int]) -> List[Int] {
  return xs.reverse().reverse()
}

test "small example" {
  assert reverse_twice([1, 2]) == [1, 2]
}

property "reverse twice changes nothing" (xs: List[Int]) {
  assert reverse_twice(xs) == xs
}
```

Property-тест проверяет утверждение на сотне случайных входов. Если найдётся провал, Klar **сожмёт** пример до
минимального, например `xs = [0, 1]`, чтобы причину было видно сразу.

Контракт тоже становится тестом. У функции с `ensures` `klar test` сам проверяет её на сотне случайных входов,
удовлетворяющих `requires`, и сообщает о нарушении как о проваленном свойстве `contract: имя` с минимальным
контрпримером. Так находятся ошибки, для которых тест ещё никто не написал: `isqrt(2) = 2` нарушает
`ensures result * result <= n`.

Падение, которое случилось один раз, можно повторить: `klar run --record run.json main.klar` записывает всё, что
программа получила снаружи (ввод, часы, случайные числа, файлы), а `klar replay run.json` запускает её снова на
тех же данных — вывод и ошибка совпадают байт в байт, даже если файлов и того ввода уже нет. То же умеет `klarc`
(`klarc run --record`, `klarc replay`), и записи у них общие.

Код с файлами, временем и случайностью тестируется без настоящего диска и часов: тест объявляет эффекты, и они
работают на подделках — пустой файловой системе в памяти, часах на нуле и одинаковых случайных числах.

```klar
fn save(name: Str, text: Str) -> Result[Unit, Str] uses fs {
  make_dir("notes")?
  return write_file("notes/{name}.txt", text)
}

test "save writes the note" uses fs, time {
  assert save("a", "hi") == Ok(())
  assert read_file("notes/a.txt") == Ok("hi")      // в памяти: на диск ничего не попало
  set_clock(1500)
  assert now_ms() == 1500
}
```

## 11. Безопасность до запуска

Klar следует принципу Rust: если ошибку можно найти при компиляции, её находит компилятор.

```mermaid
flowchart TB
    d["a / b  (Int)"] --> q{"Компилятор видит,<br/>что b ≠ 0?"}
    q -- "литерал: a / 2" --> ok["✅ компилируется"]
    q -- "if b != 0 { ... }" --> ok
    q -- "requires b != 0" --> ok
    q -- "match b { 0 => ..., _ => a / b }" --> ok
    q -- "if xs.is_empty() { return } … / xs.len()" --> ok
    q -- "var d = 3 … d = d + 2" --> ok
    q -- "не видно" --> err["❌ E0701: делитель может быть нулём<br/>+ подсказка, как доказать"]
```

Что ещё отсекается до запуска:

| ошибка | код |
|---|---|
| использовать `Option`/`Result` как обычное значение | E0211 |
| выбросить результат `push`/`trim`/`set` | E0405 |
| не обработать вариант `enum` в `match` | E0301 |
| не обработать `Result` | E0402 |
| перепутать аргументы (≥3 параметров без имён) | E0208 |
| затенить имя переменной | E0102 |
| вызвать функцию с эффектом без `uses` | E0401 |
| рекурсия без базового случая | E0702 |
| вызов, заведомо нарушающий `requires` (константы или `if n < 0 { root(n) }`) | E0703 |
| `return`, заведомо нарушающий `ensures` (`ensures result > 0` и `return 0`) | E0706 |
| `2.pow(-1)`, `(-1.0).sqrt()`, `xs.chunks(0)` | E0704 |
| `xs.get(xs.len())` — индекс всегда за границей | E0705 |
| сортировка значений без порядка | E0215 |

Каждый код объясняет `klar explain <код>`. Переполнения целых, `null`, исключений и гонок данных в Klar нет совсем.

## 12. Модули

```mermaid
flowchart LR
    main["main.klar<br/>use lib.geo.{Point, dist}<br/>use std.math.{gcd}"] --> geo["lib/geo.klar"]
    main --> std["std/math.klar<br/>(стандартный модуль)"]
    geo -. "циклы запрещены" .-x main
```

Модуль — это файл. Импорт всегда явный (`use a.b.{x, y}`), имена типов уникальны во всей программе, циклы
импорта запрещены. Поэтому, глядя на имя, всегда можно найти, откуда оно (`klar refs`).

Импортировать можно только объявления с `pub`. Всё остальное — внутреннее дело модуля:

```text
// lib/geo.klar
pub type Point { x: Float, y: Float }     // видно снаружи
fn square(v: Float) -> Float { ... }      // вспомогательная, только для этого файла
pub fn dist(p: Point) -> Float { ... }
```

Публичный интерфейс модуля — это ровно его строки с `pub`, `klar outline` показывает их первыми словами. Импорт
закрытого имени — ошибка E0606, `klar fix` сам добавит `pub`. Закрытая функция, которую никто не вызывает (тесты
считаются), — предупреждение W0406: это мёртвый код.

### Пакеты

Проект — это папка с `klar.toml` (`klar new` создаёт его). В нём перечислены зависимости:

```toml
[package]
name = "app"
version = "0.1.0"

[dependencies]
geometry = { path = "../geometry" }                                   # папка с собственным klar.toml
json5 = { git = "https://github.com/someone/json5.git", tag = "v1.2.0" }   # или rev = "...", branch = "main"
```

```mermaid
flowchart LR
    main["main.klar<br/>use geometry.{Point}<br/>use geometry.shapes.{Circle}"] --> lib["geometry/lib.klar"]
    main --> sh["geometry/shapes.klar"]
    lib --> j["json5/lib.klar<br/>(.klar/deps/json5)"]
```

Первая часть `use` — имя зависимости: `use geometry.{Point}` загружает `lib.klar` пакета, `use geometry.shapes.{...}`
— его `shapes.klar`. Модули пакета называются по нему (`geometry`, `geometry.shapes`) и не пересекаются с вашими.
Одно имя зависимости — один пакет во всей программе: если два `klar.toml` дают ему разные источники, это E0608.

| хочу | команда |
|---|---|
| добавить зависимость | `klar add json5 --git URL --tag v1.2.0` или `klar add geometry --path ../geometry` |
| получить зависимости после `git clone` | `klar fetch` (ставит коммиты из `klar.lock`) |
| обновить до новых коммитов | `klar update [имя]` |
| посмотреть дерево | `klar deps` (`--json` для агента) |
| убрать | `klar remove имя` |

git-зависимости лежат в `.klar/deps/` (в `.gitignore`), точные коммиты — в `klar.lock` (его коммитят). Центрального
реестра нет: пакет — это git-репозиторий с `klar.toml` и `lib.klar` (`klar new имя --lib`).

## 13. Как ИИ работает с Klar

```mermaid
sequenceDiagram
    participant AI as ИИ-агент
    participant K as klar
    AI->>K: klar spec (один раз в промпт, ~2 тыс. токенов)
    loop пока не «done»
        AI->>K: klar dev main.klar --json
        K-->>AI: ошибки (код, место, hint, fix) / проваленные тесты / вывод, поле next
        AI->>K: klar fix · klar doc split · klar eval '…'
    end
    AI->>K: klar coverage · klar build
    K-->>AI: покрытие, исполняемый файл
```

Чтобы поправить одну функцию в большом проекте, агенту не нужно читать файлы целиком. `klar context main.klar
file_name` (или MCP-инструмент `klar_context`) даёт исходник функции с документацией, сигнатуры типов и функций,
которые она использует, её тесты и места вызова. Всё это укладывается в бюджет `--max-tokens` (по умолчанию 2000).
Всё, что не поместилось, перечислено в строке `not shown`. Остальные инструменты тоже доступны агенту по MCP:
`klar mcp`, а без Python — `klarc mcp`.

## 14. Шпаргалка «хочу → пишу»

| хочу | пишу |
|---|---|
| неизменяемое значение / переменная | `let x = 1` / `var n = 0`, затем `n = n + 1` |
| условие-значение (тернарник) | `match ok { true => "да", false => "нет" }` |
| длина, элемент, последний | `xs.len()`, `xs.get(i)` → `Option`, `xs.last()` |
| добавить в список / словарь | `xs = xs.push(v)`, `m = m.set(k, v)` |
| пройти по числам | `for i in range(0, n) { ... }` |
| строка с числом | `"total: {n}"` |
| преобразовать | `n.to_float()`, `f.round()`, `s.to_int()` → `Option[Int]`, `x.to_str()` |
| обновить поле записи | `p with { x: 2.0 }` |
| число со смыслом и границами | `type Percent = new Int` + `requires value <= 100`, `Percent(5)`, `p.value` |
| значение по умолчанию | `opt.unwrap_or(0)` |
| пробросить ошибку | `let v = parse(s)?` |
| лямбда | `xs.map(fn(x) => x * 2)` |
| задействовать все ядра | `xs.par_map(f)` (`f` чистая; результат как у `map`) |
| отладка | `dbg(x)` печатает выражение и значение |
| заглушка | `todo("написать позже")` |
| битовые операции | `a.bit_and(b)`, `a.bit_xor(b)`, `a.shift_left(3)` (операторов `&`, `\|`, `<<` нет) |
| коды символов | `"hé".codes()` → `[104, 233]`, `65.to_char()` → `Some("A")` |
| множество | `use std.set.{set_of}`, `set_of([1, 2]).has(1)` |
| байты, двоичные файлы | `var b = bytes_of([])`, `b = b.push_le(n, 4)`, `write_bytes(path, b)` |
| JSON | `use std.json.{parse_json, lookup, json_text}`, `lookup(parse_json(text)?, "users.0.name")` |
| дата и время (UTC) | `use std.time.{now_utc, format_iso, parse_iso}`, `format_iso(now_utc())` |
| элемент или значение по умолчанию | `xs.get_or(i, 0)` |
| общий метод у разных типов | `trait Shape { fn area(self) -> Float }`, `impl Shape for Circle { ... }` |
| функция для любого типа с методом | `fn total[T: Shape](xs: List[T]) -> Float` |
| список разных фигур | `enum AnyShape { ... }` + `impl Shape for AnyShape` (трейт — не тип) |
| переменная окружения, код выхода | `env_var("HOME")` → `Option[Str]`, `exit(1)` (эффект `io`) |

Подробности по каждой функции — `klar doc <имя>`, проверить поведение — `klar eval '<выражение>'`.
