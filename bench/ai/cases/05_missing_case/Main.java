public class Main {
    sealed interface Shape permits Circle, Square, Triangle {}
    record Circle(double radius) implements Shape {}
    record Square(double side) implements Shape {}
    record Triangle(double base, double height) implements Shape {}

    static double area(Shape s) {
        return switch (s) { // BUG: Triangle is not handled
            case Circle c -> 3.14159 * c.radius() * c.radius();
            case Square q -> q.side() * q.side();
        };
    }

    public static void main(String[] args) {
        System.out.println(area(new Triangle(4.0, 3.0)));
    }
}
