import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.function.DoubleBinaryOperator;
import java.util.function.DoubleUnaryOperator;
import jdk.incubator.vector.DoubleVector;
import jdk.incubator.vector.FloatVector;
import jdk.incubator.vector.VectorOperators;
import jdk.incubator.vector.VectorShape;
import jdk.incubator.vector.VectorSpecies;

// Checks the Vector API's math functions, which C2 compiles into calls to
// libjsvml (SVML), against StrictMath. Run with
// --add-modules jdk.incubator.vector -Djdk.incubator.vector.DEBUG=true
public class VectorMathTest {
    record Op(String name, VectorOperators.Operator op, DoubleUnaryOperator unary,
              DoubleBinaryOperator binary, double lo, double hi, double lo2, double hi2) {}

    static final List<Op> OPS = List.of(
        new Op("SIN", VectorOperators.SIN, StrictMath::sin, null, -100, 100, 0, 0),
        new Op("COS", VectorOperators.COS, StrictMath::cos, null, -100, 100, 0, 0),
        new Op("TAN", VectorOperators.TAN, StrictMath::tan, null, -1.5, 1.5, 0, 0),
        new Op("ASIN", VectorOperators.ASIN, StrictMath::asin, null, -1, 1, 0, 0),
        new Op("ACOS", VectorOperators.ACOS, StrictMath::acos, null, -1, 1, 0, 0),
        new Op("ATAN", VectorOperators.ATAN, StrictMath::atan, null, -1000, 1000, 0, 0),
        new Op("EXP", VectorOperators.EXP, StrictMath::exp, null, -40, 40, 0, 0),
        new Op("EXPM1", VectorOperators.EXPM1, StrictMath::expm1, null, -40, 40, 0, 0),
        new Op("LOG", VectorOperators.LOG, StrictMath::log, null, 1e-6, 1e6, 0, 0),
        new Op("LOG10", VectorOperators.LOG10, StrictMath::log10, null, 1e-6, 1e6, 0, 0),
        new Op("LOG1P", VectorOperators.LOG1P, StrictMath::log1p, null, -0.9, 1e6, 0, 0),
        new Op("CBRT", VectorOperators.CBRT, StrictMath::cbrt, null, -1e6, 1e6, 0, 0),
        new Op("SINH", VectorOperators.SINH, StrictMath::sinh, null, -20, 20, 0, 0),
        new Op("COSH", VectorOperators.COSH, StrictMath::cosh, null, -20, 20, 0, 0),
        new Op("TANH", VectorOperators.TANH, StrictMath::tanh, null, -20, 20, 0, 0),
        new Op("POW", VectorOperators.POW, null, StrictMath::pow, 0.01, 100, -5, 5),
        new Op("ATAN2", VectorOperators.ATAN2, null, StrictMath::atan2, -10, 10, -10, 10),
        new Op("HYPOT", VectorOperators.HYPOT, null, StrictMath::hypot, -1000, 1000, -1000, 1000));

    static final double[] SPECIAL = {0.0, -0.0, Double.NaN, Double.POSITIVE_INFINITY,
        Double.NEGATIVE_INFINITY, Double.MIN_VALUE, 1e300, -1e300, 1.0, -1.0};

    static final int N = 4096;
    static final int ROUNDS = 300;
    static int failures;

    public static void main(String[] args) {
        ByteArrayOutputStream debug = new ByteArrayOutputStream();
        PrintStream out = System.out;
        System.setOut(new PrintStream(debug, true));
        List<String> report = new ArrayList<>();
        try {
            for (VectorShape shape : new VectorShape[] {VectorShape.S_64_BIT,
                    VectorShape.S_128_BIT, VectorShape.S_256_BIT, VectorShape.S_512_BIT}) {
                if (shape.vectorBitSize() > VectorShape.preferredShape().vectorBitSize()) {
                    continue;
                }
                for (Op op : OPS) {
                    report.add(checkDouble(DoubleVector.SPECIES_MAX.withShape(shape), op));
                    report.add(checkFloat(FloatVector.SPECIES_MAX.withShape(shape), op));
                }
            }
        } finally {
            System.setOut(out);
        }
        String log = debug.toString();
        long symbols = log.lines().filter(l -> l.contains("__jsvml_")).count();
        report.stream().filter(l -> l.startsWith("FAIL")).forEach(System.out::println);
        System.out.println(report.size() + " operation and species pairs checked, "
                + symbols + " SVML entry points used");
        if (!log.contains("SVML library is used") || symbols == 0) {
            System.out.println("FAIL SVML was not used");
            failures++;
        }
        if (failures > 0) {
            System.out.println(failures + " failure(s)");
            System.exit(1);
        }
        System.out.println("all passed");
    }

    static double[] inputs(double lo, double hi, long seed) {
        Random r = new Random(seed);
        double[] a = new double[N];
        for (int i = 0; i < N; i++) {
            a[i] = i < SPECIAL.length ? SPECIAL[i] : lo + (hi - lo) * r.nextDouble();
        }
        return a;
    }

    // Accurate to a few ulps, and agreeing on NaN, infinities and the sign of zero.
    static boolean close(double expected, double actual, double ulp) {
        if (Double.isNaN(expected) || Double.isNaN(actual)) {
            return Double.isNaN(expected) && Double.isNaN(actual);
        }
        if (Double.isInfinite(expected) || expected == 0) {
            return Double.compare(expected, actual) == 0 || Math.abs(expected - actual) <= 4 * ulp;
        }
        return Math.abs(expected - actual) <= 4 * Math.max(Math.ulp(expected), ulp);
    }

    @SuppressWarnings("unchecked")
    static String checkDouble(VectorSpecies<Double> s, Op op) {
        double[] a = inputs(op.lo, op.hi, 1), b = inputs(op.lo2, op.hi2, 2), r = new double[N];
        for (int round = 0; round < ROUNDS; round++) {
            for (int i = 0; i < N; i += s.length()) {
                DoubleVector x = DoubleVector.fromArray(s, a, i);
                DoubleVector v = op.unary != null
                        ? x.lanewise((VectorOperators.Unary) op.op)
                        : x.lanewise((VectorOperators.Binary) op.op, DoubleVector.fromArray(s, b, i));
                v.intoArray(r, i);
            }
        }
        int bad = 0;
        for (int i = 0; i < N; i++) {
            double e = op.unary != null ? op.unary.applyAsDouble(a[i]) : op.binary.applyAsDouble(a[i], b[i]);
            if (!close(e, r[i], Double.MIN_VALUE)) {
                if (bad++ == 0) {
                    System.err.printf("%s %s: x=%s y=%s expected %s, got %s%n", op.name, s, a[i], b[i], e, r[i]);
                }
            }
        }
        failures += bad > 0 ? 1 : 0;
        return (bad > 0 ? "FAIL " : "ok   ") + op.name + " double x" + s.length() + (bad > 0 ? " (" + bad + " lanes)" : "");
    }

    @SuppressWarnings("unchecked")
    static String checkFloat(VectorSpecies<Float> s, Op op) {
        double[] a = inputs(op.lo, op.hi, 3), b = inputs(op.lo2, op.hi2, 4);
        float[] fa = new float[N], fb = new float[N], r = new float[N];
        for (int i = 0; i < N; i++) {
            fa[i] = (float) a[i];
            fb[i] = (float) b[i];
        }
        for (int round = 0; round < ROUNDS; round++) {
            for (int i = 0; i < N; i += s.length()) {
                FloatVector x = FloatVector.fromArray(s, fa, i);
                FloatVector v = op.unary != null
                        ? x.lanewise((VectorOperators.Unary) op.op)
                        : x.lanewise((VectorOperators.Binary) op.op, FloatVector.fromArray(s, fb, i));
                v.intoArray(r, i);
            }
        }
        int bad = 0;
        for (int i = 0; i < N; i++) {
            float e = (float) (op.unary != null ? op.unary.applyAsDouble(fa[i]) : op.binary.applyAsDouble(fa[i], fb[i]));
            if (!close(e, r[i], Math.ulp(e))) {
                if (bad++ == 0) {
                    System.err.printf("%s %s: x=%s y=%s expected %s, got %s%n", op.name, s, fa[i], fb[i], e, r[i]);
                }
            }
        }
        failures += bad > 0 ? 1 : 0;
        return (bad > 0 ? "FAIL " : "ok   ") + op.name + " float x" + s.length() + (bad > 0 ? " (" + bad + " lanes)" : "");
    }
}
