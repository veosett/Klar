import java.util.*;

public class Main {
    public static void main(String[] args) {
        List<String> names = List.of("ann", "bob", "cat");
        System.out.println(names.length()); // BUG: name from another language
    }
}
