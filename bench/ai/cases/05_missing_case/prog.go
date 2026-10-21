package main

import "fmt"

type Kind int

const (
	Circle Kind = iota
	Square
	Triangle
)

type Shape struct {
	Kind              Kind
	A, B              float64
}

func area(s Shape) float64 {
	switch s.Kind { // BUG: Triangle is not handled
	case Circle:
		return 3.14159 * s.A * s.A
	case Square:
		return s.A * s.A
	}
	return 0
}

func main() {
	fmt.Printf("%.1f\n", area(Shape{Triangle, 4, 3}))
}
