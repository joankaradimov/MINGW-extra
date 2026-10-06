import org.jd.core.v1.ClassFileToJavaSourceDecompiler;
import org.jd.core.v1.api.loader.Loader;
import org.jd.core.v1.api.loader.LoaderException;
import org.jd.core.v1.api.printer.Printer;

import javax.tools.ToolProvider;
import java.io.IOException;
import java.nio.file.*;
import java.util.List;

// Decompiles class files compiled by the running JDK.
public class TestJdCore {
    static final String SAMPLE = """
        public class Sample {
            enum Color { RED, GREEN }
            record Point(int x, int y) {}
            class Inner { int twice(int v) { return v * 2; } }
            static String greet(String name, int n) { return "Hello, " + name + " x" + n; }
        }
        """;

    static int failures;

    static void expect(boolean ok, String what) {
        System.out.println((ok ? "ok    " : "FAIL  ") + what);
        if (!ok) failures++;
    }

    static String decompile(Path dir, String internalName) throws Exception {
        Loader loader = new Loader() {
            public boolean canLoad(String name) { return Files.exists(dir.resolve(name + ".class")); }
            public byte[] load(String name) throws LoaderException {
                try {
                    return Files.readAllBytes(dir.resolve(name + ".class"));
                } catch (IOException e) {
                    throw new LoaderException(e);
                }
            }
        };
        StringBuilder sb = new StringBuilder();
        Printer printer = new Printer() {
            int indent;
            public void start(int maxLineNumber, int majorVersion, int minorVersion) {}
            public void end() {}
            public void printText(String text) { sb.append(text); }
            public void printNumericConstant(String constant) { sb.append(constant); }
            public void printStringConstant(String constant, String owner) { sb.append(constant); }
            public void printKeyword(String keyword) { sb.append(keyword); }
            public void printDeclaration(int type, String internalName, String name, String descriptor) { sb.append(name); }
            public void printReference(int type, String internalName, String name, String descriptor, String owner) { sb.append(name); }
            public void indent() { indent++; }
            public void unindent() { indent--; }
            public void startLine(int lineNumber) { sb.append("    ".repeat(indent)); }
            public void endLine() { sb.append('\n'); }
            public void extraLine(int count) { sb.append("\n".repeat(count)); }
            public void startMarker(int type) {}
            public void endMarker(int type) {}
        };
        new ClassFileToJavaSourceDecompiler().decompile(loader, printer, internalName);
        return sb.toString();
    }

    public static void main(String[] args) throws Exception {
        Path dir = Paths.get(args[0]);
        Files.writeString(dir.resolve("Sample.java"), SAMPLE);
        int rc = ToolProvider.getSystemJavaCompiler().run(null, null, null,
            "-d", dir.toString(), dir.resolve("Sample.java").toString());
        expect(rc == 0, "javac compiles the sample");

        String source = "";
        try {
            source = decompile(dir, "Sample");
            expect(true, "Sample decompiles");
        } catch (Exception e) {
            e.printStackTrace();
            expect(false, "Sample decompiles: " + e);
        }
        for (String part : List.of("enum Color", "RED, GREEN", "class Inner", "* 2",
                "\"Hello, \" + ", "\" x\"", "public int x()")) {
            expect(source.contains(part), "output has " + part);
        }

        if (failures != 0)
            System.out.print(source);
        System.out.println(failures == 0 ? "test-jd-core: passed" : "test-jd-core: " + failures + " failed");
        System.exit(failures == 0 ? 0 : 1);
    }
}
