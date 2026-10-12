# 4 KiB random read and write latency of a drive, one request at a time, bypassing the Windows file cache (S1 of the paper handoff).
# Equivalent to: fio --rw=randread / randwrite --bs=4k --iodepth=1 --direct=1 (fio is not installed and cannot be here).
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File io_latency.ps1 -Dir C:\xv6_iotest -SizeMB 1024 -Reads 5000 -Writes 5000
# Creates one test file in -Dir, deletes it at the end. Prints one CSV line per test: drive, test, ops, median_us, mean_us, p95_us, p99_us, max_us.
param([string]$Dir, [int]$SizeMB = 1024, [int]$Reads = 5000, [int]$Writes = 5000, [string]$Label = "")
Add-Type -TypeDefinition @"
using System; using System.Diagnostics; using System.IO; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
public static class Io {
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] static extern SafeFileHandle CreateFile(string n, uint a, uint s, IntPtr sec, uint cd, uint fl, IntPtr t);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetFilePointerEx(SafeFileHandle h, long d, out long np, uint m);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool ReadFile(SafeFileHandle h, IntPtr b, uint n, out uint r, IntPtr o);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool WriteFile(SafeFileHandle h, IntPtr b, uint n, out uint w, IntPtr o);
  [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr VirtualAlloc(IntPtr a, UIntPtr s, uint t, uint p);
  const uint GENERIC_READ = 0x80000000, GENERIC_WRITE = 0x40000000, CREATE_ALWAYS = 2, OPEN_EXISTING = 3;
  const uint NO_BUFFERING = 0x20000000, WRITE_THROUGH = 0x80000000;
  public static string Run(string path, long sizeBytes, int reads, int writes, string label) {
    const int BS = 4096; var sb = new System.Text.StringBuilder();
    IntPtr buf = VirtualAlloc(IntPtr.Zero, (UIntPtr)(1 << 20), 0x3000, 4);          // page aligned, as unbuffered I/O needs
    long dummy; uint n; var rnd = new Random(12345);
    using (var h = CreateFile(path, GENERIC_READ | GENERIC_WRITE, 0, IntPtr.Zero, CREATE_ALWAYS, NO_BUFFERING | WRITE_THROUGH, IntPtr.Zero)) {
      if (h.IsInvalid) throw new Exception("cannot create " + path + " error " + Marshal.GetLastWin32Error());
      for (long off = 0; off < sizeBytes; off += (1 << 20)) { WriteFile(h, buf, (uint)(1 << 20), out n, IntPtr.Zero); }   // allocate the whole file
      long blocks = sizeBytes / BS;
      foreach (var test in new[] { "randread", "randwrite" }) {
        int ops = test == "randread" ? reads : writes; var lat = new double[ops];
        double tick = 1e6 / Stopwatch.Frequency;
        for (int i = 0; i < ops; i++) {
          long off = (long)(rnd.NextDouble() * blocks) * BS; SetFilePointerEx(h, off, out dummy, 0);
          long t0 = Stopwatch.GetTimestamp();
          bool ok = test == "randread" ? ReadFile(h, buf, (uint)BS, out n, IntPtr.Zero) : WriteFile(h, buf, (uint)BS, out n, IntPtr.Zero);
          lat[i] = (Stopwatch.GetTimestamp() - t0) * tick; if (!ok) throw new Exception(test + " failed " + Marshal.GetLastWin32Error());
        }
        Array.Sort(lat); double sum = 0; foreach (var x in lat) sum += x;
        sb.AppendLine(string.Format("{0},{1},{2},{3:F0},{4:F0},{5:F0},{6:F0},{7:F0}", label, test, ops, lat[ops / 2], sum / ops, lat[(int)(ops * 0.95)], lat[(int)(ops * 0.99)], lat[ops - 1]));
      }
    }
    File.Delete(path); return sb.ToString();
  }
}
"@
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$path = Join-Path $Dir "xv6_iotest.bin"
if ($Label -eq "") { $Label = (Split-Path $Dir -Qualifier) }
[Io]::Run($path, [long]$SizeMB * 1MB, $Reads, $Writes, $Label)
Remove-Item -Force -ErrorAction SilentlyContinue $path
