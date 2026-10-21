public class Main {
    public static void main(String[] args) {
        String name = "  ann  ";
        name.trim(); // BUG: the trimmed copy is thrown away
        System.out.println("[" + name + "]");
    }
}
