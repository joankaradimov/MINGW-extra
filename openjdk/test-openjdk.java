import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.color.ColorSpace;
import java.awt.font.FontRenderContext;
import java.awt.image.BufferedImage;
import java.awt.image.ColorConvertOp;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.zip.CRC32;
import java.util.zip.Deflater;
import java.util.zip.Inflater;
import javax.imageio.ImageIO;

public class SmokeTest {
    static int failures;

    static void check(String what, boolean ok) {
        System.out.println((ok ? "ok   " : "FAIL ") + what);
        if (!ok) failures++;
    }

    static int[] maybeNull(int i) { return (i % 1000 == 999) ? null : new int[1]; }

    // Hot enough for C1 and C2; the null load must fault inside compiled code.
    static int nullChecks() {
        int caught = 0;
        for (int i = 0; i < 200_000; i++) {
            try {
                caught += maybeNull(i)[0];
            } catch (NullPointerException e) {
                caught++;
            }
        }
        return caught;
    }

    static int divisions(int d) {
        int caught = 0;
        for (int i = 0; i < 200_000; i++) {
            try {
                caught += i / ((i % 1000 == 999) ? 0 : d);
                caught -= i / d;
            } catch (ArithmeticException e) {
                caught++;
            }
        }
        return caught;
    }

    static int depth;
    static void recurse() { depth++; recurse(); }

    public static void main(String[] args) throws Exception {
        System.out.println(System.getProperty("java.vm.name") + " "
                + System.getProperty("java.runtime.version"));

        check("implicit null checks", nullChecks() == 200);
        check("integer division by zero", divisions(7) == 200);
        try {
            recurse();
            check("stack overflow", false);
        } catch (StackOverflowError e) {
            check("stack overflow (depth " + depth + ")", depth > 1000);
        }
        check("MIN_VALUE / -1", Integer.MIN_VALUE / Integer.parseInt("-1") == Integer.MIN_VALUE);

        AtomicLong sum = new AtomicLong();
        var pool = Executors.newFixedThreadPool(8);
        for (int t = 0; t < 64; t++) {
            pool.submit(() -> { for (int i = 1; i <= 10_000; i++) sum.addAndGet(i); });
        }
        pool.shutdown();
        check("threads", pool.awaitTermination(60, TimeUnit.SECONDS) && sum.get() == 64L * 50_005_000L);

        long kept = 0;
        for (int i = 0; i < 2_000; i++) {
            byte[] b = new byte[1 << 20];
            kept += b.length;
        }
        System.gc();
        check("allocation and GC", kept == 2_000L << 20);

        byte[] text = "The quick brown fox jumps over the lazy dog".repeat(1000)
                .getBytes(StandardCharsets.UTF_8);
        CRC32 crc = new CRC32();
        crc.update(text, 0, 43);
        Deflater def = new Deflater();
        def.setInput(text);
        def.finish();
        byte[] packed = new byte[text.length];
        int n = def.deflate(packed);
        Inflater inf = new Inflater();
        inf.setInput(packed, 0, n);
        byte[] back = new byte[text.length];
        int m = inf.inflate(back);
        check("zlib", crc.getValue() == 0x414FA339L && m == text.length
                && java.util.Arrays.equals(text, back));

        Path tmp = Files.createTempFile("smoke", ".txt");
        Files.writeString(tmp, "héllo wörld");
        check("files", Files.readString(tmp).equals("héllo wörld"));
        Files.delete(tmp);

        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getLoopbackAddress());
             Socket client = new Socket(InetAddress.getLoopbackAddress(), server.getLocalPort());
             Socket peer = server.accept()) {
            client.getOutputStream().write(42);
            check("sockets", peer.getInputStream().read() == 42);
        }

        BufferedImage img = new BufferedImage(64, 32, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = img.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,
                RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        g.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 20));
        g.drawString("Jg", 4, 24);
        g.dispose();
        int lit = 0;
        for (int y = 0; y < 32; y++)
            for (int x = 0; x < 64; x++)
                if ((img.getRGB(x, y) & 0xffffff) != 0) lit++;
        check("font rendering", lit > 20);
        char[] arabic = "مرحبا".toCharArray();
        var glyphs = new Font(Font.SANS_SERIF, Font.PLAIN, 20).layoutGlyphVector(
                new FontRenderContext(null, true, true), arabic, 0, arabic.length,
                Font.LAYOUT_RIGHT_TO_LEFT);
        check("text shaping", glyphs.getNumGlyphs() > 0
                && glyphs.getLogicalBounds().getWidth() > 0);

        for (String fmt : new String[] {"png", "jpg", "gif"}) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            boolean wrote = ImageIO.write(img, fmt, out);
            BufferedImage read = ImageIO.read(new ByteArrayInputStream(out.toByteArray()));
            check("image " + fmt, wrote && read != null && read.getWidth() == 64);
        }

        ColorConvertOp gray = new ColorConvertOp(ColorSpace.getInstance(ColorSpace.CS_GRAY), null);
        BufferedImage grey = gray.filter(img, null);
        check("color management", grey.getWidth() == 64);

        if (failures > 0) {
            System.out.println(failures + " failure(s)");
            System.exit(1);
        }
        System.out.println("all passed");
    }
}
