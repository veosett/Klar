import java.util.*;
public class Strings {
    public static void main(String[] args) {
        long a = System.nanoTime();
        List<String> parts = new ArrayList<>();
        for (int i = 0; i < 100000; i++) parts.add("item" + i);
        String joined = String.join(",", parts);
        String[] back = joined.split(",");
        long sevens = Arrays.stream(back).filter(s -> s.endsWith("7")).count();
        double ms = (System.nanoTime() - a) / 1e6;
        System.out.println("result=" + sevens + "," + joined.length());
        System.out.printf("time_ms=%.3f%n", ms);
    }
}
