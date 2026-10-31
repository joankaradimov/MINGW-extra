# Analyzes test-pyghidra.exe through PyGhidra and decompiles its checksum
# function. Started without GHIDRA_INSTALL_DIR or JAVA_HOME, PyGhidra must
# find the Ghidra and the JDK of this Python's prefix.
import sys
from pathlib import Path

import pyghidra

binary, project = sys.argv[1:3]
pyghidra.start()

from ghidra.framework import Application  # noqa: E402 (needs the JVM)
from java.lang import System  # noqa: E402

prefix = Path(sys.base_prefix).resolve()
ghidra = Path(str(Application.getInstallationDirectory().getAbsolutePath())).resolve()
java_home = Path(str(System.getProperty('java.home'))).resolve()
print('Ghidra:', ghidra)
print('JDK:', java_home)
assert ghidra == prefix / 'lib' / 'ghidra', ghidra
assert java_home.is_relative_to(prefix / 'lib' / 'jvm'), java_home

Path(project).mkdir(parents=True, exist_ok=True)
with pyghidra.open_project(project, 'test', create=True) as ghidra_project:
    from ghidra.app.decompiler import DecompInterface

    with pyghidra.program_loader().project(ghidra_project).source(binary).load() as loaded:
        loaded.save(pyghidra.task_monitor())

    with pyghidra.program_context(ghidra_project, '/' + Path(binary).name) as program:
        pyghidra.analyze(program)
        checksum = next((f for f in program.getFunctionManager().getFunctions(True)
                         if 'pyghidra_checksum' in f.getName()), None)
        assert checksum is not None, 'the exported checksum function was not found'

        decompiler = DecompInterface()
        try:
            assert decompiler.openProgram(program), decompiler.getLastMessage()
            results = decompiler.decompileFunction(checksum, 60, pyghidra.task_monitor())
            assert results.decompileCompleted(), results.getErrorMessage()
            c = str(results.getDecompiledFunction().getC())
            print(c)
            # h = 5381, in whichever form the decompiler prints it
            assert '0x1505' in c or '5381' in c, 'the decompiled checksum lacks its seed'
        finally:
            decompiler.dispose()

print('test-pyghidra: passed')
