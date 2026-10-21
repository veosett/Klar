package main

import (
	"fmt"
	"strings"
	"time"
)

func main() {
	a := time.Now()
	parts := make([]string, 100000)
	for i := range parts {
		parts[i] = fmt.Sprintf("item%d", i)
	}
	joined := strings.Join(parts, ",")
	back := strings.Split(joined, ",")
	sevens := 0
	for _, s := range back {
		if strings.HasSuffix(s, "7") {
			sevens++
		}
	}
	ms := float64(time.Since(a).Nanoseconds()) / 1e6
	fmt.Printf("result=%d,%d\ntime_ms=%.3f\n", sevens, len(joined), ms)
}
