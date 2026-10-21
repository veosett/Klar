public class Fib {
    static long fib(long n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
    public static void main(String[] args) {
        long a = System.nanoTime();
        long r = fib(25);
        double ms = (System.nanoTime() - a) / 1e6;
        System.out.println("result=" + r);
        System.out.printf("time_ms=%.3f%n", ms);
    }
}
