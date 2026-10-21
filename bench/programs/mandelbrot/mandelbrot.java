public class Mandelbrot {
    public static void main(String[] args) {
        long a = System.nanoTime();
        long inside = 0;
        for (int y = 0; y < 60; y++) for (int x = 0; x < 120; x++) {
            double cr = x / 120.0 * 3.5 - 2.5, ci = y / 60.0 * 2.0 - 1.0, zr = 0.0, zi = 0.0; int k = 0;
            while (k < 50 && zr * zr + zi * zi <= 4.0) { double t = zr * zr - zi * zi + cr; zi = 2.0 * zr * zi + ci; zr = t; k++; }
            if (k == 50) inside++;
        }
        double ms = (System.nanoTime() - a) / 1e6;
        System.out.println("result=" + inside);
        System.out.printf("time_ms=%.3f%n", ms);
    }
}
