import org.jd.gui.api.model.Container;
import org.jd.gui.api.model.Type;
import org.jd.gui.service.type.ClassFileTypeFactoryProvider;

import javax.tools.ToolProvider;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

// Reads class files compiled by the running JDK with jd-gui's own type
// factory (ASM), and finds jd-core through the jar's Class-Path.
public class TestJdGui {
    static final String SAMPLE = """
        public class Sample {
            enum Color { RED, GREEN }
            record Point(int x, int y) {}
            sealed interface Shape permits Circle {}
            static final class Circle implements Shape {}
            class Inner { Inner(int v) {} }
            static String greet(String name) { return "Hello, " + name; }
        }
        """;

    static int failures;

    static void expect(boolean ok, String what) {
        System.out.println((ok ? "ok    " : "FAIL  ") + what);
        if (!ok) failures++;
    }

    static Container.Entry entry(Path file, Container.Entry[] parent, List<Container.Entry> children) {
        return (Container.Entry) Proxy.newProxyInstance(TestJdGui.class.getClassLoader(),
            new Class<?>[] { Container.Entry.class }, (self, m, a) -> switch (m.getName()) {
                case "getUri" -> file.toUri();
                case "getPath" -> file.getFileName().toString();
                case "getParent" -> parent[0];
                case "getChildren" -> children;
                case "isDirectory" -> children != null;
                case "length" -> Files.size(file);
                case "getInputStream" -> Files.newInputStream(file);
                case "hashCode" -> System.identityHashCode(self);
                case "equals" -> self == a[0];
                case "toString" -> file.toString();
                default -> null;
            });
    }

    static Set<String> names(Collection<?> members) throws Exception {
        Set<String> names = new TreeSet<>();
        if (members == null)
            return names;
        for (Object member : members) {
            Method getName = member.getClass().getMethod("getName");
            getName.setAccessible(true);
            names.add((String) getName.invoke(member));
        }
        return names;
    }

    public static void main(String[] args) throws Exception {
        Path dir = Paths.get(args[0]);
        Files.writeString(dir.resolve("Sample.java"), SAMPLE);
        int rc = ToolProvider.getSystemJavaCompiler().run(null, null, null,
            "-d", dir.toString(), dir.resolve("Sample.java").toString());
        expect(rc == 0, "javac compiles the sample");

        List<Container.Entry> classes = new ArrayList<>();
        Container.Entry[] root = { null };
        root[0] = entry(dir, new Container.Entry[] { null }, classes);
        try (Stream<Path> files = Files.list(dir)) {
            for (Path file : files.filter(f -> f.toString().endsWith(".class")).sorted().toList()) {
                classes.add(entry(file, root, null));
            }
        }

        ClassFileTypeFactoryProvider factory = new ClassFileTypeFactoryProvider();
        Map<String, Type> types = new TreeMap<>();
        for (Container.Entry e : classes) {
            try {
                Type type = factory.make(null, e, null);
                types.put(type.getName(), type);
                names(type.getInnerTypes());
            } catch (Exception | Error ex) {
                expect(false, e.getPath() + ": " + ex);
            }
        }
        System.out.println("types: " + types.keySet());

        expect(types.containsKey("Sample"), "Sample read");
        if (types.containsKey("Sample")) {
            Type sample = types.get("Sample");
            expect(names(sample.getMethods()).contains("greet"), "Sample.greet listed");
            expect(names(sample.getInnerTypes()).containsAll(
                List.of("Sample$Color", "Sample$Point", "Sample$Shape", "Sample$Circle", "Sample$Inner")),
                "Sample's inner types listed: " + names(sample.getInnerTypes()));
        }
        if (types.containsKey("Sample$Point")) {
            Set<String> methods = names(types.get("Sample$Point").getMethods());
            expect(methods.containsAll(List.of("x", "y")), "record accessors listed: " + methods);
        } else {
            expect(false, "record Sample$Point read");
        }
        expect(types.containsKey("Sample$Shape"), "sealed interface Sample$Shape read");

        // jd-gui shows the JD-Core-Version it finds in a manifest on its class path.
        Class<?> persister = Class.forName("org.jd.gui.service.configuration.ConfigurationXmlPersisterProvider");
        Method version = persister.getDeclaredMethod("getJdCoreVersion");
        version.setAccessible(true);
        Object jdCoreVersion = version.invoke(persister.getDeclaredConstructor().newInstance());
        expect(!"SNAPSHOT".equals(jdCoreVersion), "JD-Core-Version found: " + jdCoreVersion);
        expect(Class.forName("org.jd.core.v1.ClassFileToJavaSourceDecompiler") != null, "jd-core loads");

        System.out.println(failures == 0 ? "test-jd-gui: passed" : "test-jd-gui: " + failures + " failed");
        System.exit(failures == 0 ? 0 : 1);
    }
}
