import java.util.stream.*;
public class Collections {
    public static void main(String[] args) {
        long a = System.nanoTime();
        long[] ys = LongStream.range(0, 200000).map(x -> (x * 7919) % 10007).filter(x -> x % 2 == 0).sorted().toArray();
        long total = LongStream.of(ys).sum();
        long median = ys[ys.length / 2];
        double ms = (System.nanoTime() - a) / 1e6;
        System.out.println("result=" + ys.length + "," + total + "," + median);
        System.out.printf("time_ms=%.3f%n", ms);
    }
}
