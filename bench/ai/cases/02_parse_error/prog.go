package main

import (
	"fmt"
	"strconv"
)

func doubleQuantity(text string) int {
	qty, _ := strconv.Atoi(text)
	return qty * 2 // BUG: the text may not be a number
}

func main() {
	fmt.Println(doubleQuantity("12a"))
}
