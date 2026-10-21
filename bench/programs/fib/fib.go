package main

import (
	"fmt"
	"time"
)

func fib(n int64) int64 {
	if n < 2 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

func main() {
	a := time.Now()
	r := fib(25)
	ms := float64(time.Since(a).Nanoseconds()) / 1e6
	fmt.Printf("result=%d\ntime_ms=%.3f\n", r, ms)
}
