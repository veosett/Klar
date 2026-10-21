package main

import (
	"fmt"
	"strings"
)

func main() {
	name := "  ann  "
	strings.TrimSpace(name) // BUG: the trimmed copy is thrown away
	fmt.Printf("[%s]\n", name)
}
