param([string]$OutPath, [string]$ProcessName = "PacketTracer")
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PtWin {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@
$p = Get-Process | Where-Object { $_.ProcessName -like "$ProcessName*" -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { [Console]::Error.WriteLine("No se encontró la ventana de Packet Tracer"); exit 2 }
$h = $p.MainWindowHandle
if ([PtWin]::IsIconic($h)) { [PtWin]::ShowWindow($h, 9) | Out-Null }   # SW_RESTORE
$r = New-Object PtWin+RECT
[PtWin]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [PtWin]::PrintWindow($h, $hdc, 2)        # PW_RENDERFULLCONTENT
$g.ReleaseHdc($hdc)
if (-not $ok) {                                  # plan B: traer al frente y copiar de pantalla
  [PtWin]::SetForegroundWindow($h) | Out-Null
  Start-Sleep -Milliseconds 400
  $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
}
$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
