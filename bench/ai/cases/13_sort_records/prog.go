package main

import (
	"fmt"
	"slices"
	"strings"
)

type Person struct {
	Name string
	Age  int
}

func main() {
	people := []Person{{"cat", 3}, {"ann", 1}, {"bob", 2}}
	slices.Sort(people) // BUG: Person has no order; meant sort by age
	names := []string{}
	for _, p := range people {
		names = append(names, p.Name)
	}
	fmt.Println(strings.Join(names, ","))
}
