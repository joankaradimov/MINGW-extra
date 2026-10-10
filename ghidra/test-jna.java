// Runs JNA from the jars the package ships, on the jnidispatch.dll built here:
// a call into Windows, a callback back into Java, and, unless given "yajsw",
// Ghidra's own use of JNA: a ConPTY running cmd.exe.

import java.io.InputStream;
import java.util.concurrent.TimeUnit;

import com.sun.jna.Native;
import com.sun.jna.platform.win32.Kernel32;
import com.sun.jna.platform.win32.User32;

import ghidra.pty.Pty;
import ghidra.pty.PtyFactory;
import ghidra.pty.PtySession;

public class TestJna {

	public static void main(String[] args) throws Exception {
		// JNA's protected mode needs Visual C++'s __try, so a MinGW build has
		// none; that tells this jnidispatch.dll from the one upstream ships.
		Native.setProtected(true);
		check(!Native.isProtected(), "JNA did not load the jnidispatch.dll built here");

		check(Kernel32.INSTANCE.GetCurrentProcessId() == ProcessHandle.current().pid(),
			"GetCurrentProcessId through JNA");
		int[] windows = { 0 };
		User32.INSTANCE.EnumWindows((hwnd, data) -> {
			windows[0]++;
			return true;
		}, null);
		check(windows[0] > 0, "EnumWindows called back into Java");

		if (args.length == 0) {
			try (Pty pty = PtyFactory.local().openpty()) {
				PtySession session = pty.getChild()
						.session(new String[] { "cmd.exe", "/c", "echo test-jna-pty" }, null);
				InputStream in = pty.getParent().getInputStream();
				StringBuffer seen = new StringBuffer();
				Thread reader = new Thread(() -> {
					byte[] buf = new byte[4096];
					try {
						for (int n; (n = in.read(buf)) > 0;) {
							seen.append(new String(buf, 0, n));
						}
					}
					catch (Exception e) {
						// closing the pty ends the read
					}
				});
				reader.setDaemon(true);
				reader.start();
				check(session.waitExited(30, TimeUnit.SECONDS) == 0, "cmd.exe in the ConPTY");
				long deadline = System.currentTimeMillis() + 10000;
				while (seen.indexOf("test-jna-pty") < 0 && System.currentTimeMillis() < deadline) {
					Thread.sleep(100);
				}
				check(seen.indexOf("test-jna-pty") >= 0, "cmd.exe output read through the ConPTY");
			}
		}
		System.out.println("test-jna: passed");
		System.exit(0);
	}

	private static void check(boolean ok, String what) {
		if (!ok) {
			System.out.println("test-jna: FAILED: " + what);
			System.exit(1);
		}
	}
}
