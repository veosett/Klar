package main

import (
	"fmt"
	"sort"
	"time"
)

func main() {
	a := time.Now()
	ys := []int64{}
	for x := int64(0); x < 200000; x++ {
		v := (x * 7919) % 10007
		if v%2 == 0 {
			ys = append(ys, v)
		}
	}
	sort.Slice(ys, func(i, j int) bool { return ys[i] < ys[j] })
	var total int64
	for _, v := range ys {
		total += v
	}
	median := ys[len(ys)/2]
	ms := float64(time.Since(a).Nanoseconds()) / 1e6
	fmt.Printf("result=%d,%d,%d\ntime_ms=%.3f\n", len(ys), total, median, ms)
}
