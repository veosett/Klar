public class Main {
    static int doubleQuantity(String text) {
        int qty = Integer.parseInt(text);
        return qty * 2; // BUG: the text may not be a number
    }

    public static void main(String[] args) {
        System.out.println(doubleQuantity("12a"));
    }
}
