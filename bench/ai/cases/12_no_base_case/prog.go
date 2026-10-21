package main

import "fmt"

func fact(n int) int {
	return n * fact(n-1) // BUG: no base case
}

func main() {
	fmt.Println(fact(5))
}
