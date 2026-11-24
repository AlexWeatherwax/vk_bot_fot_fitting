# Shared helpers compatible with Windows PowerShell 5.1.
Set-StrictMode -Version 2.0

function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Value)
    # ProcessStartInfo.Arguments follows the Windows command-line quoting rules.
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Join-NativeArguments {
    param([string[]]$Values)
    return (($Values | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
}

function ConvertTo-SshConfigPath {
    param([string]$Path)
    if ($Path -match '["\r\n]') { throw 'Путь подключения содержит недопустимые символы.' }
    # ssh parses -o values a second time using its configuration grammar.
    return '"' + $Path.Replace('\', '/') + '"'
}

function Find-OpenSshTool {
    param([string]$Name)
    $native = Join-Path $env:WINDIR ('System32\OpenSSH\' + $Name + '.exe')
    if (Test-Path -LiteralPath $native -PathType Leaf) { return $native }
    $command = Get-Command ($Name + '.exe') -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw 'На компьютере не установлен «Клиент OpenSSH». Добавьте его в дополнительных компонентах Windows или обратитесь к специалисту, который настраивает мастерскую.'
}

function Protect-OwnerDirectory {
    param([string]$Path)
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    # Read and persist only the DACL. Reading/writing audit or owner sections
    # would require privileges that an ordinary Windows user does not hold.
    $acl = [IO.Directory]::GetAccessControl($Path, [Security.AccessControl.AccessControlSections]::Access)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($existing in @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))) {
        $acl.RemoveAccessRuleSpecific($existing)
    }
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    [IO.Directory]::SetAccessControl($Path, $acl)
}

function Protect-OwnerFile {
    param([string]$Path)
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [IO.File]::GetAccessControl($Path, [Security.AccessControl.AccessControlSections]::Access)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($existing in @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))) {
        $acl.RemoveAccessRuleSpecific($existing)
    }
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')
    $acl.AddAccessRule($rule)
    [IO.File]::SetAccessControl($Path, $acl)
}

function Read-EditorConfiguration {
    param([string]$Directory)
    $path = Join-Path $Directory 'config.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Настройка подключения ещё не завершена. Нужен файл config.json, подготовленный при установке сервера.'
    }
    try { $config = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'Файл подключения повреждён. Восстановите config.json из комплекта настройки.' }
    foreach ($name in @('ServerHost', 'ServerPort', 'SshUser', 'LocalPort', 'RemotePort')) {
        if (-not $config.PSObject.Properties[$name]) { throw ('В настройках отсутствует поле ' + $name + '.') }
    }
    if ([string]$config.ServerHost -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') {
        throw 'Адрес сервера ещё не указан или записан неверно. Нужен IP-адрес или имя сервера в config.json.'
    }
    if ([string]$config.SshUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') {
        throw 'В настройках неверно указано имя пользователя сервера.'
    }
    if ($config.SshUser -eq 'root') {
        throw 'Для мастерской нужен отдельный пользователь сервера с ограниченным доступом. Учётная запись root для ярлыка не подходит.'
    }
    foreach ($name in @('ServerPort', 'LocalPort', 'RemotePort')) {
        $number = 0
        if (-not [int]::TryParse([string]$config.$name, [ref]$number) -or $number -lt 1 -or $number -gt 65535) {
            throw ('В настройках неверно указан порт: ' + $name + '.')
        }
        $config.$name = $number
    }
    if ($config.LocalPort -lt 1024) { throw 'Для локального подключения нужен порт от 1024 до 65535.' }
    return $config
}

function Test-EditorEndpoint {
    param([string]$Url)
    $response = $null
    try {
        $request = [Net.HttpWebRequest]::Create($Url)
        $request.Proxy = $null
        $request.AllowAutoRedirect = $false
        $request.Timeout = 800
        $request.ReadWriteTimeout = 800
        try { $response = $request.GetResponse() }
        catch [Net.WebException] { $response = $_.Exception.Response }
        if ($null -eq $response) { return $false }
        return (($response.Headers['X-Imladris-Editor'] -eq '1') -and
            (([int]$response.StatusCode -eq 200) -or ([int]$response.StatusCode -eq 401)))
    }
    catch { return $false }
    finally { if ($null -ne $response) { $response.Close() } }
}

function Test-LocalPortAvailable {
    param([int]$Port)
    $listener = $null
    try {
        $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)
        $listener.ExclusiveAddressUse = $true
        $listener.Start()
        return $true
    }
    catch { return $false }
    finally { if ($null -ne $listener) { $listener.Stop() } }
}
