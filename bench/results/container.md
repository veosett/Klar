# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 5 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | c | cpp | rust | go | java | javascript | python | klar | klar-py | klar-interp | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 5.0 | 4.9 | 2.0 | 13.1 | 31.5 | 34.2 | 29.9 | 7.0 | 46.0 | 827 | 4.3× | 1.4× |
| fib | 0.157 | 0.123 | 0.179 | 0.331 | 0.883 | 2.3 | 8.2 | 1.1 | 8.3 | 1 203 | 7.4× | 7.1× |
| loop | 1.1 | 1.1 | 1.1 | 1.1 | 3.2 | 7.0 | 23.3 | 1.4 | 28.5 | 1 057 | 16.6× | 1.3× |
| mandelbrot | 0.278 | 0.289 | 0.301 | 0.286 | 3.2 | 5.2 | 11.8 | 1.1 | 12.0 | 985 | 10.8× | 3.9× |
| primes | 0.826 | 0.852 | 0.520 | 0.901 | 2.2 | 2.5 | 16.2 | 1.0 | 26.0 | 1 311 | 15.7× | 1.2× |
| strings | 7.4 | 9.0 | 8.4 | 14.2 | 40.4 | 28.2 | 16.5 | 13.8 | 34.1 | 514 | 1.2× | 1.9× |

Wall-clock time including process start-up (ms):

| benchmark | c | cpp | rust | go | java | javascript | python | klar | klar-py | klar-interp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 7.1 | 8.1 | 4.0 | 16.5 | 821 | 75.3 | 52.5 | 8.1 | 162 | 946 |
| fib | 2.1 | 2.5 | 1.9 | 1.9 | 714 | 43.6 | 25.1 | 1.9 | 113 | 1 360 |
| loop | 2.6 | 3.2 | 2.9 | 3.3 | 621 | 44.7 | 39.2 | 2.1 | 133 | 1 165 |
| mandelbrot | 2.0 | 2.4 | 2.5 | 2.0 | 601 | 47.2 | 28.2 | 1.7 | 119 | 1 096 |
| primes | 2.6 | 3.7 | 2.4 | 3.0 | 725 | 38.2 | 31.5 | 1.7 | 140 | 1 474 |
| strings | 9.2 | 12.0 | 11.4 | 16.9 | 768 | 65.9 | 34.4 | 17.1 | 157 | 633 |

Versions:

- **klar**: Klar 0.3, native compiler (own x86-64 codegen + linker, no libc)
- **klar-py**: Klar 0.3, Python-bytecode backend (on CPython 3.13.16)
- **klar-interp**: Klar 0.3, tree-walking interpreter (on CPython 3.13.16)
- **python**: CPython 3.13.16
- **javascript**: Node.js v22.22.0
- **c**: gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 -O2
- **cpp**: g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0 -O2
- **java**: openjdk version "21.0.12.1" 2026-08-18
- **go**: go version go1.24.7 linux/amd64
- **rust**: rustc 1.97.0 (2d8144b78 2026-07-07) -O

Result check: all languages produced identical results ✅
