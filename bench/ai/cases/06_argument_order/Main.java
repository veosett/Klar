public class Main {
    static int finalPrice(int price, int discountPercent, int taxPercent) {
        return price * (100 - discountPercent) / 100 * (100 + taxPercent) / 100;
    }

    public static void main(String[] args) {
        System.out.println(finalPrice(200, 20, 10)); // BUG: tax and discount swapped (should be discount 10, tax 20)
    }
}
