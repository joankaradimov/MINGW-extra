// Runs FlatLaf's Windows library from the jar the package ships, which holds
// only the one built here, without opening a window.

import com.formdev.flatlaf.ui.FlatNativeWindowsLibrary;

public class TestFlatLaf {

	public static void main(String[] args) {
		check(FlatNativeWindowsLibrary.isLoaded(), "FlatLaf did not load its library");
		long build = FlatNativeWindowsLibrary.getOSBuildNumber();
		System.out.println("test-flatlaf: Windows build " + build);
		check(build > 0, "getOSBuildNumber");
		// a null window must be refused without reaching DWM
		check(!FlatNativeWindowsLibrary.setWindowCornerPreference(0,
			FlatNativeWindowsLibrary.DWMWCP_ROUND), "setWindowCornerPreference(0)");
		System.out.println("test-flatlaf: passed");
	}

	private static void check(boolean ok, String what) {
		if (!ok) {
			System.out.println("test-flatlaf: failed: " + what);
			System.exit(1);
		}
	}
}
