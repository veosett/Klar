package main

import "fmt"

func main() {
	xs := []int{10, 20, 30}
	fmt.Printf("last=%d\n", xs[len(xs)]) // BUG: off by one
}
