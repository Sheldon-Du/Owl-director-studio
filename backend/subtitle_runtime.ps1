param([string]$RuntimeRoot,[string]$Script,[string]$InputFile,[string]$OutputFile,[string]$ModelPath)
$ErrorActionPreference='Stop'
$dll=Join-Path $RuntimeRoot 'python310.dll'
if (!(Test-Path -LiteralPath $dll)) { throw 'pyVideoTrans Python 3.10 runtime missing' }
$escaped=$dll.Replace('\','\\').Replace('"','\"')
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class OwlSubtitlePython {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] public static extern bool SetDllDirectory(string path);
 [DllImport("$escaped",CallingConvention=CallingConvention.Cdecl,CharSet=CharSet.Unicode)] public static extern void Py_SetPath(string path);
 [DllImport("$escaped",CallingConvention=CallingConvention.Cdecl)] public static extern int Py_Main(int argc,IntPtr argv);
}
"@
[OwlSubtitlePython]::SetDllDirectory($RuntimeRoot) | Out-Null
$runtimePath=(Join-Path $RuntimeRoot 'base_library.zip')+';'+$RuntimeRoot
[OwlSubtitlePython]::Py_SetPath($runtimePath)
$arguments=@('owl-subtitles','-S','-X','utf8',$Script,$InputFile,$OutputFile,$ModelPath)
$pointers=@($arguments | ForEach-Object {[Runtime.InteropServices.Marshal]::StringToHGlobalUni($_)})
$argv=[Runtime.InteropServices.Marshal]::AllocHGlobal([IntPtr]::Size*$pointers.Count)
try {
 for($i=0;$i -lt $pointers.Count;$i++){[Runtime.InteropServices.Marshal]::WriteIntPtr($argv,$i*[IntPtr]::Size,$pointers[$i])}
 $code=[OwlSubtitlePython]::Py_Main($pointers.Count,$argv)
} finally {
 foreach($pointer in $pointers){[Runtime.InteropServices.Marshal]::FreeHGlobal($pointer)}
 [Runtime.InteropServices.Marshal]::FreeHGlobal($argv)
}
exit $code
