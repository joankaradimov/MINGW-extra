# @runtime Jython
# Runs in analyzeHeadless with the Jython extension installed. Jython's os
# module calls the system through jnr-posix, which falls back to plain Java
# without a word when jffi's native library fails to load.

import os

from java.lang import Class

# Jython's own instance; the class itself is visible only as the nt module
posix = Class.forName("org.python.modules.posix.PosixModule").getMethod("getPOSIX").invoke(None)
if not posix.isNative():
    raise Exception("jnr-posix fell back to Java: jffi did not load")
script = getSourceFile().getAbsolutePath()
print("jython: pid %d, %s is %d bytes" % (os.getpid(), os.path.basename(script),
                                          os.stat(script).st_size))
# analyzeHeadless logs a failing script and still exits 0
print("test-jython: passed")
