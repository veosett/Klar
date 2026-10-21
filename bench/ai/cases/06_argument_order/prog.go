package main

import "fmt"

func finalPrice(price, discountPercent, taxPercent int) int {
	return price * (100 - discountPercent) / 100 * (100 + taxPercent) / 100
}

func main() {
	fmt.Println(finalPrice(200, 20, 10)) // BUG: tax and discount swapped (should be discount 10, tax 20)
}
