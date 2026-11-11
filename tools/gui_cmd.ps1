param(
    [int]$Port = 8765,
    [Parameter(Mandatory = $true)][string]$Cmd,
    [string]$Params = "{}"
)

$ErrorActionPreference = "Stop"
$client = [System.Net.Sockets.TcpClient]::new("127.0.0.1", $Port)
try {
    $stream = $client.GetStream()
    $writer = [System.IO.StreamWriter]::new($stream)
    $writer.AutoFlush = $true
    $request = @{
        id = 1
        cmd = $Cmd
        params = ($Params | ConvertFrom-Json)
    } | ConvertTo-Json -Compress -Depth 8
    $writer.WriteLine($request)

    $reader = [System.IO.StreamReader]::new($stream)
    $response = $reader.ReadLine() | ConvertFrom-Json
    if (-not $response.ok) { throw $response.error }
    $response.result | ConvertTo-Json -Compress -Depth 6
}
finally {
    $client.Close()
}
