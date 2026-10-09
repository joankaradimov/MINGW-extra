#!/bin/sh
dir=$(cd "$(dirname "$0")" && pwd)
JAVA_HOME=${JAVA_HOME:-$dir/../lib/jvm/@JVMDIR@}
export JAVA_HOME
exec "$dir/../share/ant/bin/ant" "$@"
