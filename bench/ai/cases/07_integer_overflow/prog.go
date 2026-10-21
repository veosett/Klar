package main

import "fmt"

func factorial(n int64) int64 {
	var r int64 = 1
	for i := int64(2); i <= n; i++ {
		r = r * i // BUG?: overflows in most languages
	}
	return r
}

func main() {
	fmt.Println(factorial(25))
}
