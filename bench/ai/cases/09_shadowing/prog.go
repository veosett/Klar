package main

import "fmt"

func main() {
	n := 42
	label := "small"
	if n > 10 {
		label := "big" // BUG: declares a new variable instead of assigning
	}
	fmt.Println(label)
}
