# AI-ergonomics benchmark: when is a typical AI mistake caught?

| mistake | Klar | Python | Python + mypy | TypeScript (strict) | Java | Go (+ vet) | Rust | C++ (-Wall -Wextra) |
|---|---|---|---|---|---|---|---|---|
| Look up a key that may be missing — *uses the result of a map lookup as if the key were always present* | ✅ compile | 💥 runtime | ✅ compile | ✅ compile | 💥 runtime | ❌ silent | 💥 runtime | ❌ silent |
| Parse a number from text — *assumes the text is a valid number* | ✅ compile | 💥 runtime | 💥 runtime | ❌ silent | 💥 runtime | ❌ silent | 💥 runtime | ❌ silent |
| Average of a list that can be empty — *divides by the length without checking for an empty list* | ✅ compile | 💥 runtime | 💥 runtime | ❌ silent | 💥 runtime | 💥 runtime | 💥 runtime | 💥 runtime |
| Normalize a string — *calls trim/strip expecting it to modify the string in place* | ✅ compile | ❌ silent | ❌ silent | ❌ silent | ❌ silent | ❌ silent | ⚠️ warning | ❌ silent |
| Handle every variant of an enum — *forgets a newly added variant* | ✅ compile | ❌ silent | ✅ compile | ✅ compile | ✅ compile | ❌ silent | ✅ compile | ⚠️ warning |
| Call a function with several same-typed parameters — *passes two arguments in the wrong order* | ✅ compile | ❌ silent | ❌ silent | ❌ silent | ❌ silent | ❌ silent | ❌ silent | ❌ silent |
| Compute 25! — *uses a fixed-size integer for a value that does not fit* | 🛡️ by design | 🛡️ by design | 🛡️ by design | ❌ silent | ❌ silent | ❌ silent | 💥 runtime | ❌ silent |
| Take the last element of a list — *indexes one past the end* | ✅ compile | 💥 runtime | 💥 runtime | ❌ silent | 💥 runtime | 💥 runtime | 💥 runtime | ❌ silent |
| Update a variable inside a branch — *declares a new variable instead of assigning the outer one* | ✅ compile | n/a | n/a | ❌ silent | ✅ compile | ✅ compile | ⚠️ warning | ❌ silent |
| Get the length of a list — *uses the method name from another language* | ✅ compile | 💥 runtime | ✅ compile | ✅ compile | ✅ compile | ✅ compile | ✅ compile | ✅ compile |
| Build a message with a number — *adds a number to a string* | ✅ compile | 💥 runtime | ✅ compile | 🛡️ by design | 🛡️ by design | ✅ compile | ✅ compile | ❌ silent |
| Recursive factorial — *forgets the base case of the recursion* | ✅ compile | 💥 runtime | 💥 runtime | 💥 runtime | 💥 runtime | 💥 runtime | ⚠️ warning | 💥 runtime |
| Sort records — *sorts records that have no order (forgets the key)* | ✅ compile | 💥 runtime | ✅ compile | ❌ silent | ✅ compile | ✅ compile | ✅ compile | ✅ compile |

| summary | Klar | Python | Python + mypy | TypeScript (strict) | Java | Go (+ vet) | Rust | C++ (-Wall -Wextra) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **safety score** (compile/design = 1, warning = ½, runtime = ¼, silent = 0) | **100** | **25** | **58** | **33** | **48** | **37** | **52** | **23** |
| stopped before running (compile error or impossible by design) | 13/13 | 1/12 | 6/12 | 4/13 | 5/13 | 4/13 | 4/13 | 2/13 |
| only a warning | 0/13 | 0/12 | 0/12 | 0/13 | 0/13 | 0/13 | 3/13 | 1/13 |
| crash at run time | 0/13 | 8/12 | 4/12 | 1/13 | 5/13 | 3/13 | 5/13 | 2/13 |
| **silently wrong result** | **0/13** | **3/12** | **2/12** | **8/13** | **3/13** | **6/13** | **1/13** | **8/13** |
| message points at the mistaken line | 12/12 | 7/8 | 7/9 | 2/4 | 8/9 | 7/7 | 10/12 | 3/5 |
| message suggests a fix | 12/12 | 0/8 | 0/9 | 0/4 | 0/9 | 0/7 | 6/12 | 0/5 |
| average message size, tokens | 96 | 83 | 55 | 60 | 1028 | 463 | 154 | 543 |

✅ rejected by the compiler / type checker · 🛡️ the mistake cannot happen (correct result) · ⚠️ compiled with a warning at the mistake · 💥 crashed at run time · ❌ wrong result, no error

Machine: Linux x86_64, Python 3.13.16.
