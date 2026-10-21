# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 5 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | c | rust | go | java | javascript | python | klar | klar-py | klar-interp | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 4.5 | 2.3 | 13.3 | 39.3 | 28.5 | 23.3 | 6.6 | 45.0 | 707 | 3.5× | 1.5× |
| fib | 0.117 | 0.179 | 0.340 | 0.539 | 2.0 | 7.9 | 1.0 | 8.7 | 1 221 | 7.8× | 8.7× |
| loop | 1.1 | 0.980 | 1.1 | 3.8 | 7.1 | 24.1 | 1.6 | 26.7 | 1 162 | 15.1× | 1.5× |
| mandelbrot | 0.253 | 0.266 | 0.224 | 2.9 | 4.3 | 11.3 | 1.1 | 13.0 | 918 | 10.7× | 4.2× |
| primes | 0.832 | 0.585 | 0.867 | 1.8 | 2.1 | 16.5 | 1.1 | 19.3 | 1 238 | 14.7× | 1.3× |
| strings | 8.4 | 9.2 | 16.7 | 48.3 | 35.2 | 17.6 | 12.4 | 30.0 | 522 | 1.4× | 1.5× |

Wall-clock time including process start-up (ms):

| benchmark | c | rust | go | java | javascript | python | klar | klar-py | klar-interp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 6.2 | 4.3 | 16.8 | 765 | 58.3 | 40.1 | 8.0 | 163 | 823 |
| fib | 1.6 | 2.1 | 2.0 | 650 | 43.0 | 24.3 | 1.7 | 133 | 1 363 |
| loop | 2.7 | 2.7 | 3.1 | 704 | 40.3 | 40.6 | 2.4 | 144 | 1 297 |
| mandelbrot | 1.4 | 1.9 | 1.8 | 575 | 33.5 | 27.3 | 1.6 | 123 | 1 038 |
| primes | 2.2 | 2.6 | 2.9 | 594 | 33.4 | 32.4 | 1.8 | 110 | 1 356 |
| strings | 10.5 | 12.8 | 21.8 | 839 | 82.7 | 35.8 | 15.2 | 147 | 646 |

Versions:

- **klar**: Klar 0.3, native compiler (own x86-64 codegen + linker, no libc)
- **klar-py**: Klar 0.3, Python-bytecode backend (on CPython 3.13.16)
- **klar-interp**: Klar 0.3, tree-walking interpreter (on CPython 3.13.16)
- **python**: CPython 3.13.16
- **javascript**: Node.js v22.22.0
- **c**: gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 -O2
- **java**: openjdk version "21.0.12.1" 2026-08-18
- **go**: go version go1.24.7 linux/amd64
- **rust**: rustc 1.97.0 (2d8144b78 2026-07-07) -O

Result check: all languages produced identical results ✅
