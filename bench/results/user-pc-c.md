# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 3 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | java | klar-interp | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|
| collections | 37.7 | 1 219 | — | — |
| fib | 0.649 | 1 695 | — | — |
| loop | 5.0 | 1 843 | — | — |
| mandelbrot | 3.7 | 1 654 | — | — |
| primes | 4.9 | 2 035 | — | — |
| strings | 72.7 | 695 | — | — |

Wall-clock time including process start-up (ms):

| benchmark | java | klar-interp |
|---|---:|---:|
| collections | 646 | 1 510 |
| fib | 543 | 1 991 |
| loop | 592 | 2 115 |
| mandelbrot | 539 | 1 930 |
| primes | 526 | 2 302 |
| strings | 708 | 945 |

Versions:

- **klar-interp**: Klar 0.3, tree-walking interpreter (on CPython 3.10.12)
- **java**: openjdk version "11.0.32.1" 2026-08-18

Result check: all languages produced identical results ✅
