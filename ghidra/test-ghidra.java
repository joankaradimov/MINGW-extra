// Runs after analyzeHeadless has imported and analyzed test-ghidra.exe. Fails
// unless the decompiler and the GNU demangler, both native executables, work.

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.app.util.demangler.gnu.GnuDemanglerNativeProcess;
import ghidra.program.model.listing.Function;

public class TestGhidra extends GhidraScript {

	private static final String MANGLED = "_ZN11ghidra_test8checksumEPKc";

	@Override
	protected void run() throws Exception {
		String demangled =
			GnuDemanglerNativeProcess.getDemanglerNativeProcess().demangle(MANGLED);
		println("demangler_gnu: " + demangled);
		if (!demangled.contains("ghidra_test::checksum(char const*)")) {
			throw new Exception("unexpected demangling: " + demangled);
		}

		Function checksum = null;
		for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
			if (f.getName().contains("checksum")) {
				checksum = f;
				break;
			}
		}
		if (checksum == null) {
			throw new Exception("the exported checksum function was not found");
		}

		DecompInterface decompiler = new DecompInterface();
		try {
			if (!decompiler.openProgram(currentProgram)) {
				throw new Exception(decompiler.getLastMessage());
			}
			DecompileResults results = decompiler.decompileFunction(checksum, 60, monitor);
			if (!results.decompileCompleted()) {
				throw new Exception(results.getErrorMessage());
			}
			String c = results.getDecompiledFunction().getC();
			println(c);
			// h = 5381 and h * 33, in whichever form the decompiler prints them
			if (!c.contains("0x1505") && !c.contains("5381")) {
				throw new Exception("the decompiled checksum lacks its seed");
			}
		}
		finally {
			decompiler.dispose();
		}
		// analyzeHeadless logs a failing script and still exits 0
		println("test-ghidra: passed");
	}
}
