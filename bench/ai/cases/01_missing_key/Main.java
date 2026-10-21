import java.util.*;

public class Main {
    static int nextYearAge(Map<String, Integer> ages, String name) {
        return ages.get(name) + 1; // BUG: the key may be missing
    }

    public static void main(String[] args) {
        Map<String, Integer> ages = new HashMap<>(Map.of("ann", 31, "bob", 42));
        System.out.println(nextYearAge(ages, "cat"));
    }
}
