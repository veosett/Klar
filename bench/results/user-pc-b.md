# Klar benchmarks

Machine: `Linux x86_64`, 2 CPU, x86_64. Best of 5 runs. Compute time in milliseconds (measured inside each program, start-up excluded).

| benchmark | c | javascript | python | klar | klar-py | Klar speed-up vs Python | Klar time ÷ C |
|---|---:|---:|---:|---:|---:|---:|---:|
| collections | 5.1 | 43.1 | 39.3 | 10.0 | 65.6 | 3.9× | 2.0× |
| primes | 1.9 | 2.9 | 23.9 | 3.6 | 35.5 | 6.7× | 1.8× |
| strings | 11.6 | 36.3 | 28.5 | 19.9 | 51.6 | 1.4× | 1.7× |

Wall-clock time including process start-up (ms):

| benchmark | c | javascript | python | klar | klar-py |
|---|---:|---:|---:|---:|---:|
| collections | 6.0 | 96.8 | 73.2 | 11.1 | 342 |
| primes | 2.8 | 57.4 | 58.9 | 4.1 | 302 |
| strings | 12.9 | 92.7 | 63.3 | 24.7 | 331 |

Versions:

- **klar**: Klar 0.3, native compiler (own x86-64 codegen + linker, no libc)
- **klar-py**: Klar 0.3, Python-bytecode backend (on CPython 3.10.12)
- **python**: CPython 3.10.12
- **javascript**: Node.js v22.23.2
- **c**: gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0 -O2

Result check: all languages produced identical results ✅
