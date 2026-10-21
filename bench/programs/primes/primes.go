package main

import (
	"fmt"
	"time"
)

func isPrime(n int64) bool {
	if n < 2 {
		return false
	}
	if n%2 == 0 {
		return n == 2
	}
	for d := int64(3); d*d <= n; d += 2 {
		if n%d == 0 {
			return false
		}
	}
	return true
}

func main() {
	a := time.Now()
	count := 0
	for n := int64(0); n < 30000; n++ {
		if isPrime(n) {
			count++
		}
	}
	ms := float64(time.Since(a).Nanoseconds()) / 1e6
	fmt.Printf("result=%d\ntime_ms=%.3f\n", count, ms)
}
