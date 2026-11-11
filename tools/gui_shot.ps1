param(
    [int]$Port = 8765,
    [string]$Out = "$env:TEMP\opensees_gui.png",
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$client = [System.Net.Sockets.TcpClient]::new("127.0.0.1", $Port)
try {
    $stream = $client.GetStream()
    $writer = [System.IO.StreamWriter]::new($stream)
    $writer.AutoFlush = $true
    $request = @{
        id = 1
        cmd = "screenshot"
        params = @{ viewport_only = (-not $Full) }
    } | ConvertTo-Json -Compress
    $writer.WriteLine($request)

    $reader = [System.IO.StreamReader]::new($stream)
    $line = $reader.ReadLine()
    $response = $line | ConvertFrom-Json
    if (-not $response.ok) { throw $response.error }

    $bytes = [Convert]::FromBase64String($response.result.png_base64)
    $dir = Split-Path -Parent $Out
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllBytes($Out, $bytes)
    "saved $Out ($($response.result.width)x$($response.result.height), $($bytes.Length) bytes)"
}
finally {
    $client.Close()
}
