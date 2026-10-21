# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 5 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | c | cpp | rust | go | java | javascript | python | klar | klar-py | klar-interp | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 4.0 | 4.5 | 2.1 | 13.5 | 36.3 | 28.8 | 21.4 | 7.0 | 46.2 | 752 | 3.1× | 1.7× |
| fib | 0.131 | 0.109 | 0.213 | 0.336 | 0.975 | 2.0 | 7.8 | 1.0 | 7.3 | 1 066 | 7.8× | 7.7× |
| loop | 1.1 | 1.1 | 1.2 | 0.941 | 3.3 | 5.8 | 30.2 | 1.4 | 29.7 | 1 048 | 21.3× | 1.3× |
| mandelbrot | 0.269 | 0.302 | 0.244 | 0.250 | 2.9 | 4.3 | 11.7 | 0.330 | 12.8 | 983 | 35.3× | 1.2× |
| primes | 0.795 | 0.770 | 0.463 | 0.808 | 1.9 | 2.9 | 16.7 | 1.1 | 23.8 | 1 250 | 15.4× | 1.4× |
| strings | 7.6 | 8.8 | 7.5 | 14.1 | 45.7 | 29.3 | 16.0 | 12.5 | 31.4 | 476 | 1.3× | 1.7× |

Wall-clock time including process start-up (ms):

| benchmark | c | cpp | rust | go | java | javascript | python | klar | klar-py | klar-interp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collections | 5.5 | 7.3 | 4.5 | 17.2 | 738 | 66.6 | 36.9 | 8.2 | 163 | 871 |
| fib | 1.7 | 2.1 | 2.3 | 1.9 | 691 | 36.7 | 22.9 | 1.9 | 117 | 1 218 |
| loop | 2.9 | 3.8 | 3.0 | 2.6 | 616 | 49.9 | 51.5 | 2.2 | 159 | 1 177 |
| mandelbrot | 1.6 | 3.0 | 1.9 | 1.9 | 640 | 34.6 | 29.7 | 0.961 | 119 | 1 119 |
| primes | 2.3 | 2.6 | 1.9 | 2.6 | 601 | 38.5 | 32.8 | 1.8 | 145 | 1 349 |
| strings | 9.3 | 11.7 | 10.4 | 16.7 | 760 | 66.1 | 33.4 | 15.4 | 143 | 614 |

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
