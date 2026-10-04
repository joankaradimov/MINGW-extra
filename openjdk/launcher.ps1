#!/usr/bin/env pwsh
$basedir=Split-Path $MyInvocation.MyCommand.Definition -Parent
$name=[System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Definition)

$path=$env:PATH
$env:PATH="$basedir;$env:PATH"
try {
  # Support pipeline input
  if ($MyInvocation.ExpectingInput) {
    $input | & "$basedir/../lib/jvm/@JVMDIR@/bin/$name.exe"   $args
  } else {
    & "$basedir/../lib/jvm/@JVMDIR@/bin/$name.exe"   $args
  }
} finally {
  $env:PATH=$path
}
exit $LASTEXITCODE
