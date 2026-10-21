public class Main {
    public static void main(String[] args) {
        int n = 42;
        String label = "small";
        if (n > 10) {
            String label = "big"; // BUG: declares a new variable instead of assigning
        }
        System.out.println(label);
    }
}
