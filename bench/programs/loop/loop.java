public class Loop {
    public static void main(String[] args) {
        long a = System.nanoTime();
        long total = 0;
        for (long i = 0; i < 300000; i++) total = (total + i * i) % 1000007;
        double ms = (System.nanoTime() - a) / 1e6;
        System.out.println("result=" + total);
        System.out.printf("time_ms=%.3f%n", ms);
    }
}
