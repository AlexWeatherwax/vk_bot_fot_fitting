#requires -version 5.1
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
. (Join-Path $PSScriptRoot 'Common.ps1')
[Windows.Forms.Application]::EnableVisualStyles()

$title = 'Мастерская Имладриса'
$mutex = $null
$openEvent = $null
$createdNew = $false
$script:SshProcess = $null
$script:Timer = $null
$script:ShuttingDown = $false

function Stop-EditorConnection {
    if ($null -ne $script:SshProcess) {
        try {
            if (-not $script:SshProcess.HasExited) {
                $script:SshProcess.Kill()
                $null = $script:SshProcess.WaitForExit(1000)
            }
        }
        catch { }
        finally { $script:SshProcess.Dispose(); $script:SshProcess = $null }
    }
}

try {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $mutexName = 'Local\ImladrisEditor-' + $sid
    $eventName = 'Local\ImladrisEditorOpen-' + $sid
    $mutex = New-Object Threading.Mutex($true, $mutexName, [ref]$createdNew)
    $openEvent = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::AutoReset, $eventName)
    if (-not $createdNew) {
        # Only the verified running instance may decide to open its own tunnel URL.
        $null = $openEvent.Set()
        exit 0
    }

    $script:Config = Read-EditorConfiguration $PSScriptRoot
    $script:Ssh = Find-OpenSshTool 'ssh'
    $script:PrivateKey = Join-Path $PSScriptRoot 'owner_ed25519'
    $script:KnownHosts = Join-Path $PSScriptRoot 'known_hosts'
    $script:LogPath = Join-Path $PSScriptRoot 'ssh.log'
    if (-not (Test-Path -LiteralPath $script:PrivateKey -PathType Leaf)) {
        throw 'Ключ подключения не найден. Запустите Install.cmd из комплекта мастерской или восстановите доступ с помощью специалиста.'
    }
    if (-not (Test-Path -LiteralPath $script:KnownHosts -PathType Leaf) -or
        (Get-Item -LiteralPath $script:KnownHosts).Length -eq 0) {
        throw 'Настройка ещё не завершена: отсутствует подтверждённый ключ сервера known_hosts. Получите подготовленный комплект подключения у специалиста.'
    }
    Protect-OwnerFile $script:PrivateKey
    $script:EditorUrl = 'http://127.0.0.1:' + $script:Config.LocalPort + '/'
    $script:State = 'idle'
    $script:NextAttempt = [DateTime]::UtcNow
    $script:LastProbe = [DateTime]::MinValue
    $script:UnhealthySince = [DateTime]::MinValue
    $script:AttemptCount = 0
    $script:BrowserOpened = $false

    $script:Form = New-Object Windows.Forms.Form
    $script:Form.Text = $title
    $script:Form.ClientSize = New-Object Drawing.Size(600, 280)
    $script:Form.StartPosition = 'CenterScreen'
    $script:Form.FormBorderStyle = 'FixedDialog'
    $script:Form.MaximizeBox = $false
    $script:Form.BackColor = [Drawing.Color]::FromArgb(249, 247, 241)
    $script:Form.Font = New-Object Drawing.Font('Segoe UI', 11)

    $heading = New-Object Windows.Forms.Label
    $heading.Text = 'Имладрис'
    $heading.Location = New-Object Drawing.Point(22, 16)
    $heading.Size = New-Object Drawing.Size(550, 38)
    $heading.Font = New-Object Drawing.Font('Segoe UI', 22, [Drawing.FontStyle]::Bold)
    $heading.ForeColor = [Drawing.Color]::FromArgb(32, 74, 53)
    $script:Form.Controls.Add($heading)

    $script:Status = New-Object Windows.Forms.Label
    $script:Status.Location = New-Object Drawing.Point(24, 68)
    $script:Status.Size = New-Object Drawing.Size(550, 32)
    $script:Status.Font = New-Object Drawing.Font('Segoe UI', 13, [Drawing.FontStyle]::Bold)
    $script:Form.Controls.Add($script:Status)

    $script:Detail = New-Object Windows.Forms.Label
    $script:Detail.Location = New-Object Drawing.Point(24, 108)
    $script:Detail.Size = New-Object Drawing.Size(550, 88)
    $script:Form.Controls.Add($script:Detail)

    $script:OpenButton = New-Object Windows.Forms.Button
    $script:OpenButton.Text = 'Открыть мастерскую'
    $script:OpenButton.Location = New-Object Drawing.Point(24, 218)
    $script:OpenButton.Size = New-Object Drawing.Size(204, 38)
    $script:OpenButton.BackColor = [Drawing.Color]::FromArgb(32, 74, 53)
    $script:OpenButton.ForeColor = [Drawing.Color]::White
    $script:OpenButton.FlatStyle = 'Flat'
    $script:OpenButton.Enabled = $false
    $script:Form.Controls.Add($script:OpenButton)

    $retry = New-Object Windows.Forms.Button
    $retry.Text = 'Подключиться снова'
    $retry.Location = New-Object Drawing.Point(238, 218)
    $retry.Size = New-Object Drawing.Size(200, 38)
    $script:Form.Controls.Add($retry)

    $close = New-Object Windows.Forms.Button
    $close.Text = 'Закрыть'
    $close.Location = New-Object Drawing.Point(448, 218)
    $close.Size = New-Object Drawing.Size(128, 38)
    $script:Form.Controls.Add($close)

    function Set-EditorState {
        param([string]$State, [string]$Caption, [string]$Description)
        $script:State = $State
        $script:Status.Text = $Caption
        $script:Detail.Text = $Description
        $script:OpenButton.Enabled = ($State -eq 'ready')
        if ($State -eq 'ready') { $script:Status.ForeColor = [Drawing.Color]::FromArgb(32, 110, 64) }
        elseif ($State -eq 'error') { $script:Status.ForeColor = [Drawing.Color]::FromArgb(160, 49, 40) }
        else { $script:Status.ForeColor = [Drawing.Color]::FromArgb(91, 80, 55) }
    }

    function Open-EditorBrowser {
        if (($script:State -eq 'ready') -and ($null -ne $script:SshProcess) -and
            (-not $script:SshProcess.HasExited) -and (Test-EditorEndpoint $script:EditorUrl)) {
            Start-Process -FilePath $script:EditorUrl
            return $true
        }
        return $false
    }

    function Schedule-EditorReconnect {
        param([string]$Description)
        Stop-EditorConnection
        $delays = @(2, 5, 10, 20, 30)
        $delay = $delays[[Math]::Min($script:AttemptCount, $delays.Length - 1)]
        $script:AttemptCount++
        $script:NextAttempt = [DateTime]::UtcNow.AddSeconds($delay)
        Set-EditorState 'waiting' 'Восстанавливаем подключение' ($Description + "`r`nСледующая попытка через " + $delay + ' сек. Можно оставить окно открытым.')
    }

    function Start-EditorConnection {
        Stop-EditorConnection
        if (-not (Test-LocalPortAvailable $script:Config.LocalPort)) {
            Set-EditorState 'error' 'Не удалось открыть мастерскую' 'Локальный порт подключения занят другой программой. Закройте другое подключение к мастерской и нажмите «Подключиться снова».'
            return
        }
        Set-EditorState 'connecting' 'Подключаемся к мастерской' 'Проверяем защищённое соединение с сервером. Обычно это занимает несколько секунд.'
        Set-Content -LiteralPath $script:LogPath -Value '' -Encoding ASCII
        $values = @(
            '-F', 'NUL', '-n', '-N', '-T', '-E', $script:LogPath,
            '-o', 'LogLevel=ERROR', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UpdateHostKeys=no', '-o', 'VerifyHostKeyDNS=no',
            '-o', ('UserKnownHostsFile=' + (ConvertTo-SshConfigPath $script:KnownHosts)),
            '-o', ('GlobalKnownHostsFile=' + (ConvertTo-SshConfigPath $script:KnownHosts)),
            '-o', 'IdentitiesOnly=yes', '-o', 'PasswordAuthentication=no',
            '-o', 'KbdInteractiveAuthentication=no', '-o', 'PreferredAuthentications=publickey',
            '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
            '-i', $script:PrivateKey, '-p', [string]$script:Config.ServerPort,
            '-l', [string]$script:Config.SshUser,
            '-L', ('127.0.0.1:' + $script:Config.LocalPort + ':127.0.0.1:' + $script:Config.RemotePort),
            [string]$script:Config.ServerHost
        )
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = $script:Ssh
        $info.Arguments = Join-NativeArguments $values
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $script:SshProcess = [Diagnostics.Process]::Start($info)
        $script:UnhealthySince = [DateTime]::MinValue
    }

    $script:OpenButton.Add_Click({ $null = Open-EditorBrowser })
    $retry.Add_Click({ $script:AttemptCount = 0; Start-EditorConnection })
    $close.Add_Click({ $script:Form.Close() })

    $script:Timer = New-Object Windows.Forms.Timer
    $script:Timer.Interval = 500
    $script:Timer.Add_Tick({
        if ($script:ShuttingDown) { return }
        try {
            if ($openEvent.WaitOne(0)) {
                $script:Form.WindowState = 'Normal'
                $script:Form.Activate()
                $null = Open-EditorBrowser
            }
            $now = [DateTime]::UtcNow
            if (($script:State -eq 'idle' -or $script:State -eq 'waiting') -and ($now -ge $script:NextAttempt)) {
                Start-EditorConnection
            }
            if ($null -eq $script:SshProcess) { return }
            if ($script:SshProcess.HasExited) {
                $details = ''
                if (Test-Path -LiteralPath $script:LogPath) { $details = Get-Content -LiteralPath $script:LogPath -Raw }
                if ($details -match '(?i)host key verification failed|remote host identification has changed|offending .* key') {
                    Stop-EditorConnection
                    Set-EditorState 'error' 'Не удалось подтвердить сервер' 'Ключ сервера не совпадает с сохранённым. Требуется проверка сервера специалистом. Защита подключения остаётся включённой.'
                }
                elseif ($details -match '(?i)permission denied|bad permissions|unprotected private key|invalid format|load key') {
                    Stop-EditorConnection
                    Set-EditorState 'error' 'Не удалось войти в мастерскую' 'Сервер не принял ключ доступа. Если подключение настраивается впервые, дождитесь подтверждения специалиста и нажмите «Подключиться снова».'
                }
                else { Schedule-EditorReconnect 'Связь с сервером недоступна. Проверьте интернет.' }
                return
            }
            $probeInterval = 1
            if ($script:State -eq 'ready') { $probeInterval = 5 }
            if (($now - $script:LastProbe).TotalSeconds -lt $probeInterval) { return }
            $script:LastProbe = $now
            if (Test-EditorEndpoint $script:EditorUrl) {
                $script:UnhealthySince = [DateTime]::MinValue
                $script:AttemptCount = 0
                Set-EditorState 'ready' 'Мастерская подключена' 'Украшения и изменения сохраняются на сервере. Это окно можно свернуть. Закрытие окна отключит доступ к мастерской на этом компьютере.'
                if ((-not $script:BrowserOpened) -and (Open-EditorBrowser)) {
                    $script:BrowserOpened = $true
                    $script:Form.WindowState = 'Minimized'
                }
            }
            else {
                if ($script:UnhealthySince -eq [DateTime]::MinValue) { $script:UnhealthySince = $now }
                Set-EditorState 'connecting' 'Ожидаем мастерскую на сервере' 'Соединение устанавливается или сервер восстанавливает работу. Подключение продолжится автоматически.'
                if (($now - $script:UnhealthySince).TotalSeconds -ge 25) {
                    Schedule-EditorReconnect 'Мастерская на сервере пока не отвечает.'
                }
            }
        }
        catch {
            Stop-EditorConnection
            Set-EditorState 'error' 'Не удалось подключиться' 'Перезапустите мастерскую. Если ошибка повторяется, передайте специалисту файл ssh.log из папки %LOCALAPPDATA%\Imladris.'
        }
    })
    $script:Form.Add_FormClosing({ $script:ShuttingDown = $true; $script:Timer.Stop(); Stop-EditorConnection })
    Set-EditorState 'idle' 'Открываем мастерскую' 'Подготавливаем подключение к серверу.'
    $script:Timer.Start()
    $null = $script:Form.ShowDialog()
}
catch {
    $null = [Windows.Forms.MessageBox]::Show($_.Exception.Message, $title, 'OK', 'Error')
    exit 1
}
finally {
    Stop-EditorConnection
    if ($null -ne $script:Timer) { $script:Timer.Dispose() }
    if ($null -ne $openEvent) { $openEvent.Dispose() }
    if ($null -ne $mutex) {
        if ($createdNew) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}
