#!/usr/bin/env pwsh
$basedir=Split-Path $MyInvocation.MyCommand.Definition -Parent

$path=$env:PATH
$javaHome=$env:JAVA_HOME
$env:PATH="$basedir;$env:PATH"
if (-not $env:JAVA_HOME) {
  $env:JAVA_HOME=[System.IO.Path]::GetFullPath("$basedir/../lib/jvm/@JVMDIR@")
}
try {
  # Support pipeline input
  if ($MyInvocation.ExpectingInput) {
    $input | & "$basedir/../share/ant/bin/ant.bat" $args
  } else {
    & "$basedir/../share/ant/bin/ant.bat" $args
  }
} finally {
  $env:PATH=$path
  $env:JAVA_HOME=$javaHome
}
exit $LASTEXITCODE
