// Runs in analyzeHeadless. Opens a 7z archive and a disk image through
// Ghidra's file system layer, so that 7-Zip-JBinding's native library and the
// DMG server's HFSExplorer both run, and checks what they read.
//   args: <archive.7z> <member> <member's text> <image.dmg> <app bundle name>

import java.io.File;
import java.nio.charset.StandardCharsets;

import ghidra.app.script.GhidraScript;
import ghidra.app.util.bin.ByteProvider;
import ghidra.formats.gfilesystem.*;

public class TestFormats extends GhidraScript {

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		FileSystemService fss = FileSystemService.getInstance();

		try (FileSystemRef ref = open(fss, args[0], "SevenZipFileSystem")) {
			GFileSystem fs = ref.getFilesystem();
			GFile member = find(fs, fs.lookup(null), args[1]);
			String text = new String(read(member), StandardCharsets.UTF_8);
			if (!text.equals(args[2])) {
				throw new Exception("the 7z member reads as '" + text + "'");
			}
			println("7z: " + member.getPath() + " = " + text);
		}

		try (FileSystemRef ref = open(fss, args[3], "DmgClientFileSystem")) {
			GFileSystem fs = ref.getFilesystem();
			GFile root = fs.lookup(null);
			String app = args[4] + ".app/Contents/";
			byte[] plist = read(find(fs, root, app + "Info.plist"));
			String head = new String(plist, 0, Math.min(plist.length, 8),
				StandardCharsets.ISO_8859_1);
			if (!head.startsWith("<?xml") && !head.equals("bplist00")) {
				throw new Exception("Info.plist starts with '" + head + "'");
			}
			GFile exe = find(fs, root, app + "MacOS/" + args[4]);
			byte[] macho = read(exe);
			int magic = ((macho[0] & 0xff) << 24) | ((macho[1] & 0xff) << 16) |
				((macho[2] & 0xff) << 8) | (macho[3] & 0xff);
			// universal, or a thin 64-bit Mach-O in little-endian order
			if (magic != 0xcafebabe && magic != 0xcffaedfe) {
				throw new Exception("not a Mach-O: " + Integer.toHexString(magic));
			}
			println("dmg: " + exe.getPath() + ", " + macho.length + " bytes");
		}
		// analyzeHeadless logs a failing script and still exits 0
		println("test-formats: passed");
	}

	private FileSystemRef open(FileSystemService fss, String path, String expected)
			throws Exception {
		FileSystemRef ref = fss.probeFileForFilesystem(fss.getLocalFSRL(new File(path)),
			monitor, FileSystemProbeConflictResolver.CHOOSEFIRST);
		if (ref == null) {
			throw new Exception("no file system recognizes " + path);
		}
		String got = ref.getFilesystem().getClass().getSimpleName();
		if (!got.equals(expected)) {
			ref.close();
			throw new Exception(path + " opened as " + got + ", not " + expected);
		}
		return ref;
	}

	// The first file at or below dir whose path ends with /suffix
	private GFile find(GFileSystem fs, GFile dir, String suffix) throws Exception {
		GFile found = search(fs, dir, "/" + suffix);
		if (found == null) {
			throw new Exception("nothing ends with " + suffix);
		}
		return found;
	}

	private GFile search(GFileSystem fs, GFile dir, String suffix) throws Exception {
		for (GFile f : fs.getListing(dir)) {
			GFile found = f.isDirectory() ? search(fs, f, suffix)
					: f.getPath().endsWith(suffix) ? f : null;
			if (found != null) {
				return found;
			}
		}
		return null;
	}

	private byte[] read(GFile f) throws Exception {
		try (ByteProvider bp = f.getFilesystem().getByteProvider(f, monitor)) {
			return bp.readBytes(0, bp.length());
		}
	}
}
