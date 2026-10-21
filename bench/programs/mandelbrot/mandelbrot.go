package main

import (
	"fmt"
	"time"
)

func main() {
	a := time.Now()
	inside := 0
	for y := 0; y < 60; y++ {
		for x := 0; x < 120; x++ {
			cr := float64(x)/120.0*3.5 - 2.5
			ci := float64(y)/60.0*2.0 - 1.0
			zr, zi, k := 0.0, 0.0, 0
			for k < 50 && zr*zr+zi*zi <= 4.0 {
				t := zr*zr - zi*zi + cr
				zi = 2.0*zr*zi + ci
				zr = t
				k++
			}
			if k == 50 {
				inside++
			}
		}
	}
	ms := float64(time.Since(a).Nanoseconds()) / 1e6
	fmt.Printf("result=%d\ntime_ms=%.3f\n", inside, ms)
}
