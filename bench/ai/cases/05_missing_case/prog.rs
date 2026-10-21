enum Shape {
    Circle { radius: f64 },
    Square { side: f64 },
    Triangle { base: f64, height: f64 },
}

fn area(s: &Shape) -> f64 {
    match s { // BUG: Triangle is not handled
        Shape::Circle { radius } => 3.14159 * radius * radius,
        Shape::Square { side } => side * side,
    }
}

fn main() {
    println!("{:.1}", area(&Shape::Triangle { base: 4.0, height: 3.0 }));
}
