# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 7 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | c | cpp | rust | klar | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|---:|---:|
| collections | 5.6 | 6.0 | 3.0 | 20.6 | — | 3.7× |
| fib | 0.162 | 0.154 | 0.237 | 0.900 | — | 5.6× |
| loop | 1.0 | 0.994 | 0.992 | 1.8 | — | 1.7× |
| mandelbrot | 0.392 | 0.401 | 0.360 | 1.1 | — | 2.9× |
| primes | 2.0 | 2.0 | 0.939 | 3.6 | — | 1.9× |
| strings | 15.1 | 32.5 | 20.6 | 48.6 | — | 3.2× |

Wall-clock time including process start-up (ms):

| benchmark | c | cpp | rust | klar |
|---|---:|---:|---:|---:|
| collections | 6.8 | 18.4 | 4.5 | 31.8 |
| fib | 1.3 | 2.2 | 1.7 | 1.6 |
| loop | 2.2 | 2.9 | 2.5 | 2.5 |
| mandelbrot | 1.5 | 2.4 | 1.9 | 1.9 |
| primes | 3.2 | 3.9 | 2.3 | 4.4 |
| strings | 29.9 | 37.9 | 32.1 | 63.8 |

Versions:

- **klar**: Klar 0.3, native compiler (own x86-64 codegen + linker, no libc)
- **c**: gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0 -O2
- **cpp**: g++ (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0 -O2
- **rust**: rustc 1.99.1 (58cf8f9c3 2026-10-13) -O

Result check: all languages produced identical results ✅
