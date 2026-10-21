# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 5 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | c | cpp | rust | go | java | javascript | python | klar | klar-py | klar-interp | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 5.0 | 4.1 | 2.2 | 12.5 | 40.2 | 33.9 | 26.5 | 7.1 | 52.0 | 840 | 3.7× | 1.4× |
| fib | 0.112 | 0.113 | 0.164 | 0.336 | 1.0 | 2.2 | 8.1 | 0.711 | 7.0 | 1 141 | 11.3× | 6.3× |
| loop | 1.0 | 1.0 | 1.1 | 1.0 | 3.3 | 6.9 | 24.4 | 1.5 | 29.6 | 1 194 | 16.7× | 1.4× |
| mandelbrot | 0.270 | 0.288 | 0.254 | 0.279 | 3.4 | 5.3 | 10.5 | 0.371 | 13.7 | 1 012 | 28.4× | 1.4× |
| primes | 0.840 | 0.839 | 0.601 | 0.850 | 2.9 | 2.6 | 15.7 | 1.0 | 25.1 | 1 261 | 15.1× | 1.2× |
| strings | 8.2 | 9.9 | 9.4 | 15.5 | 40.2 | 33.0 | 17.9 | 13.3 | 32.7 | 529 | 1.3× | 1.6× |

Wall-clock time including process start-up (ms):

| benchmark | c | cpp | rust | go | java | javascript | python | klar | klar-py | klar-interp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 6.7 | 6.8 | 4.4 | 14.6 | 820 | 77.8 | 45.3 | 8.6 | 213 | 1 021 |
| fib | 1.5 | 2.2 | 2.0 | 2.2 | 641 | 37.7 | 24.7 | 1.3 | 122 | 1 267 |
| loop | 2.6 | 2.8 | 3.8 | 2.8 | 710 | 43.2 | 40.1 | 2.5 | 202 | 1 355 |
| mandelbrot | 2.0 | 2.6 | 2.0 | 2.5 | 696 | 46.7 | 25.6 | 0.984 | 150 | 1 162 |
| primes | 2.3 | 3.2 | 2.8 | 2.7 | 681 | 38.8 | 32.0 | 1.9 | 157 | 1 395 |
| strings | 10.5 | 13.3 | 12.8 | 17.9 | 798 | 83.3 | 37.4 | 16.4 | 165 | 657 |

Versions:

- **klar**: Klar 0.5, native compiler (own x86-64 codegen + linker, no libc)
- **klar-py**: Klar 0.5, Python-bytecode backend (on CPython 3.13.16)
- **klar-interp**: Klar 0.5, tree-walking interpreter (on CPython 3.13.16)
- **python**: CPython 3.13.16
- **javascript**: Node.js v22.22.0
- **c**: gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 -O2
- **cpp**: g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 -O2
- **java**: openjdk version "21.0.12.1" 2026-08-18
- **go**: go version go1.24.7 linux/amd64
- **rust**: rustc 1.97.0 (2d8144b78 2026-07-07) -O

Result check: all languages produced identical results ✅
