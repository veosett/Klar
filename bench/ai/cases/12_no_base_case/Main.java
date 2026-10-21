public class Main {
    static long fact(long n) {
        return n * fact(n - 1); // BUG: no base case
    }

    public static void main(String[] args) {
        System.out.println(fact(5));
    }
}
