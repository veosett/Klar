package main

import "fmt"

func nextYearAge(ages map[string]int, name string) int {
	return ages[name] + 1 // BUG: the key may be missing
}

func main() {
	ages := map[string]int{"ann": 31, "bob": 42}
	fmt.Println(nextYearAge(ages, "cat"))
}
