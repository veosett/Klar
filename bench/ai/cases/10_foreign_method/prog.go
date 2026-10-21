package main

import "fmt"

func main() {
	names := []string{"ann", "bob", "cat"}
	fmt.Println(names.len()) // BUG: name from another language
}
