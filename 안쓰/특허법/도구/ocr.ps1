# Windows 내장 OCR(한국어)로 폴더의 p###.png 를 읽어 같은 이름의 .json 을 쓴다 (이미 있으면 건너뜀).
# Windows PowerShell 5 로 돌린다(WinRT): powershell.exe -NoProfile -ExecutionPolicy Bypass -File ocr.ps1 -Dir <폴더>
# json = { "lines": [ { "text": "...", "words": [ { "t": "...", "x":0, "y":0, "w":0, "h":0 } ] } ] }  (화소 단위)
param([Parameter(Mandatory = $true)][string]$Dir)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result }
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null
$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('ko'))
if ($null -eq $eng) { Write-Error "no Korean OCR engine"; exit 1 }
$n = 0
Get-ChildItem -Path $Dir -Filter 'p*.png' | Sort-Object Name | ForEach-Object {
    $out = [IO.Path]::ChangeExtension($_.FullName, '.json')
    if (Test-Path $out) { return }
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($_.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($l in $res.Lines) {
        $ws = @()
        foreach ($w in $l.Words) {
            $r = $w.BoundingRect
            $ws += [ordered]@{ t = $w.Text; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height }
        }
        $lines += [ordered]@{ text = $l.Text; words = $ws }
    }
    $json = ([ordered]@{ lines = $lines }) | ConvertTo-Json -Depth 6 -Compress
    [IO.File]::WriteAllText($out, $json, (New-Object Text.UTF8Encoding($false)))
    $stream.Dispose()
    $n++
}
Write-Output "OCR $n pages"
