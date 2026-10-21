package main

import "fmt"

func average(xs []int) int {
	sum := 0
	for _, x := range xs {
		sum += x
	}
	return sum / len(xs) // BUG: the list may be empty
}

func main() {
	fmt.Println(average([]int{}))
}
