#requires -version 5.1
# Pure configuration/quoting checks; no server, GUI or installed SSH client needed.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
$script:Checks = 0

function Assert-Equal {
    param($Actual, $Expected, [string]$Name)
    if ($Actual -cne $Expected) { throw ($Name + ': expected <' + $Expected + '>, got <' + $Actual + '>.') }
    $script:Checks++
}

function Assert-Throws {
    param([scriptblock]$Action, [string]$Name)
    $thrown = $false
    try { $null = & $Action } catch { $thrown = $true }
    if (-not $thrown) { throw ($Name + ': expected validation error.') }
    $script:Checks++
}

Assert-Equal (ConvertTo-NativeArgument '') '""' 'Empty key passphrase is preserved'
Assert-Equal (ConvertTo-NativeArgument 'a b') '"a b"' 'Spaces stay inside argument'
Assert-Equal (ConvertTo-NativeArgument 'a"b') '"a\"b"' 'Embedded quote is escaped'
Assert-Equal (ConvertTo-NativeArgument 'C:\space path\') '"C:\space path\\"' 'Trailing slash is doubled'
Assert-Equal (ConvertTo-SshConfigPath 'C:\Users\Owner Name\known_hosts') '"C:/Users/Owner Name/known_hosts"' 'SSH config path has its own quotes'
Assert-Equal (ConvertTo-NativeArgument ('UserKnownHostsFile=' + (ConvertTo-SshConfigPath 'C:\Owner Name\known_hosts'))) '"UserKnownHostsFile=\"C:/Owner Name/known_hosts\""' 'Both parsing layers preserve spaced path'
Assert-Throws { ConvertTo-SshConfigPath "C:\key`nother" } 'Reject newline in SSH config path'

$directory = Join-Path ([IO.Path]::GetTempPath()) ('imladris-client-test-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $directory
try {
    Assert-Throws { Read-EditorConfiguration $directory } 'Missing configuration'
    $path = Join-Path $directory 'config.json'
    Set-Content -LiteralPath $path -Value 'not json' -Encoding UTF8
    Assert-Throws { Read-EditorConfiguration $directory } 'Malformed configuration'

    $valid = @{ ServerHost = '203.0.113.10'; ServerPort = 22; SshUser = 'imladris-editor'; LocalPort = 8765; RemotePort = 8765 }
    Set-Content -LiteralPath $path -Value ($valid | ConvertTo-Json) -Encoding UTF8
    $parsed = Read-EditorConfiguration $directory
    Assert-Equal $parsed.ServerHost '203.0.113.10' 'Valid host'
    Assert-Equal $parsed.LocalPort 8765 'Valid local port'

    foreach ($invalid in @(
        @{ ServerHost = '-oProxyCommand=bad' },
        @{ ServerHost = 'host;other' },
        @{ ServerHost = '' },
        @{ SshUser = 'root' },
        @{ SshUser = '-bad' },
        @{ SshUser = 'user@host' },
        @{ ServerPort = 0 },
        @{ LocalPort = 80 },
        @{ RemotePort = 65536 },
        @{ ServerPort = 22.5 }
    )) {
        $candidate = $valid.Clone()
        foreach ($name in $invalid.Keys) { $candidate[$name] = $invalid[$name] }
        Set-Content -LiteralPath $path -Value ($candidate | ConvertTo-Json) -Encoding UTF8
        Assert-Throws { Read-EditorConfiguration $directory } ('Invalid ' + ($invalid.Keys -join ','))
    }
    $valid.Remove('RemotePort')
    Set-Content -LiteralPath $path -Value ($valid | ConvertTo-Json) -Encoding UTF8
    Assert-Throws { Read-EditorConfiguration $directory } 'Missing required port'
}
finally { Remove-Item -LiteralPath $directory -Recurse -Force }
Write-Output ('PASS: ' + $script:Checks + ' client checks')
