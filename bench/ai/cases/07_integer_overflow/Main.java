public class Main {
    static long factorial(int n) {
        long r = 1;
        for (int i = 2; i <= n; i++) {
            r = r * i; // BUG?: overflows in most languages
        }
        return r;
    }

    public static void main(String[] args) {
        System.out.println(factorial(25));
    }
}
