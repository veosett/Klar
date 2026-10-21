public class Main {
    public static void main(String[] args) {
        int[] xs = {10, 20, 30};
        System.out.println("last=" + xs[xs.length]); // BUG: off by one
    }
}
