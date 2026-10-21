public class Primes {
    static boolean isPrime(long n) {
        if (n < 2) return false;
        if (n % 2 == 0) return n == 2;
        for (long d = 3; d * d <= n; d += 2) if (n % d == 0) return false;
        return true;
    }
    public static void main(String[] args) {
        long a = System.nanoTime();
        long count = 0;
        for (long n = 0; n < 30000; n++) if (isPrime(n)) count++;
        double ms = (System.nanoTime() - a) / 1e6;
        System.out.println("result=" + count);
        System.out.printf("time_ms=%.3f%n", ms);
    }
}
