package main

import (
	"fmt"
	"time"
)

func main() {
	a := time.Now()
	var total int64
	for i := int64(0); i < 300000; i++ {
		total = (total + i*i) % 1000007
	}
	ms := float64(time.Since(a).Nanoseconds()) / 1e6
	fmt.Printf("result=%d\ntime_ms=%.3f\n", total, ms)
}
