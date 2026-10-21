import java.util.*;

public class Main {
    static int average(List<Integer> xs) {
        return xs.stream().mapToInt(Integer::intValue).sum() / xs.size(); // BUG: the list may be empty
    }

    public static void main(String[] args) {
        System.out.println(average(new ArrayList<>()));
    }
}
