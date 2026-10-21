# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 5 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | c | javascript | python | klar | klar-py | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|---:|---:|---:|
| fib | 0.157 | 2.3 | 18.6 | 1.1 | 18.5 | 17.5× | 6.8× |
| loop | 0.984 | 6.4 | 41.6 | 1.3 | 46.4 | 31.5× | 1.3× |
| mandelbrot | 0.384 | 5.2 | 21.9 | 1.1 | 23.6 | 20.3× | 2.8× |

Wall-clock time including process start-up (ms):

| benchmark | c | javascript | python | klar | klar-py |
|---|---:|---:|---:|---:|---:|
| fib | 0.972 | 59.5 | 51.0 | 1.6 | 281 |
| loop | 1.9 | 64.8 | 76.4 | 1.8 | 319 |
| mandelbrot | 1.2 | 63.4 | 55.5 | 1.6 | 294 |

Versions:

- **klar**: Klar 0.3, native compiler (own x86-64 codegen + linker, no libc)
- **klar-py**: Klar 0.3, Python-bytecode backend (on CPython 3.10.12)
- **python**: CPython 3.10.12
- **javascript**: Node.js v22.23.2
- **c**: gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0 -O2

Result check: all languages produced identical results ✅
