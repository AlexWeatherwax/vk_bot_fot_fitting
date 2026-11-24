#requires -version 5.1
$ErrorActionPreference = 'Stop'
$title = 'Мастерская Имладриса'
$guiReady = $false
try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'Этот установщик предназначен для Windows 10 и Windows 11.'
    }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $guiReady = $true
    . (Join-Path $PSScriptRoot 'Common.ps1')
    $keygen = Find-OpenSshTool 'ssh-keygen'
    $null = Find-OpenSshTool 'ssh'
    $directory = Join-Path $env:LOCALAPPDATA 'Imladris'
    $null = New-Item -ItemType Directory -Path $directory -Force
    Protect-OwnerDirectory $directory

    foreach ($name in @('Start.ps1', 'Common.ps1', 'Launch.cmd', 'Show-Key.cmd')) {
        $source = Join-Path $PSScriptRoot $name
        $destination = Join-Path $directory $name
        if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($destination)) {
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
    }
    # An updated deployment bundle may replace connection details, never the owner's key.
    foreach ($name in @('config.json', 'known_hosts')) {
        $source = Join-Path $PSScriptRoot $name
        $destination = Join-Path $directory $name
        if ((Test-Path -LiteralPath $source -PathType Leaf) -and
            ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($destination))) {
            $replace = $true
            if ((Test-Path -LiteralPath $destination -PathType Leaf) -and
                ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash)) {
                $answer = [Windows.Forms.MessageBox]::Show(
                    'В комплекте есть новые настройки подключения. Применить их? Делайте это для комплекта, полученного от специалиста, который настраивает сервер.',
                    $title, 'YesNo', 'Question')
                $replace = ($answer -eq [Windows.Forms.DialogResult]::Yes)
            }
            if ($replace) { Copy-Item -LiteralPath $source -Destination $destination -Force }
        }
    }

    $key = Join-Path $directory 'owner_ed25519'
    $publicKey = $key + '.pub'
    $createdKey = $false
    if (-not (Test-Path -LiteralPath $key -PathType Leaf)) {
        if (Test-Path -LiteralPath $publicKey) {
            throw 'Найден публичный ключ без личного ключа. Обратитесь к специалисту для восстановления доступа; новый ключ автоматически не создаётся.'
        }
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = $keygen
        $info.Arguments = Join-NativeArguments @('-q', '-t', 'ed25519', '-f', $key, '-N', '', '-C', 'imladris-owner')
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $process = [Diagnostics.Process]::Start($info)
        if (-not $process.WaitForExit(15000)) {
            $process.Kill()
            throw 'Создание ключа заняло слишком много времени. Попробуйте установку ещё раз.'
        }
        if ($process.ExitCode -ne 0) { throw 'Windows не удалось создать ключ подключения.' }
        $process.Dispose()
        $createdKey = $true
    }
    Protect-OwnerFile $key
    if (-not (Test-Path -LiteralPath $publicKey -PathType Leaf)) {
        throw 'Файл публичного ключа отсутствует. Обратитесь к специалисту для восстановления файла owner_ed25519.pub.'
    }

    function New-EditorShortcut {
        param([string]$Folder, [string]$Name)
        if ([string]::IsNullOrWhiteSpace($Folder)) { throw 'Windows не вернула папку для ярлыка.' }
        $null = New-Item -ItemType Directory -Path $Folder -Force
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $Folder $Name))
        $shortcut.TargetPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $shortcut.Arguments = '-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File ' +
            (ConvertTo-NativeArgument (Join-Path $directory 'Start.ps1'))
        $shortcut.WorkingDirectory = $directory
        $shortcut.Description = 'Открыть каталог и редактор украшений Имладриса'
        $shortcut.IconLocation = (Join-Path $env:WINDIR 'System32\shell32.dll') + ',13'
        $shortcut.Save()
    }

    # Shortcuts are optional: a redirected or protected Desktop must not abort installation.
    # Launch.cmd always opens this user's installed copy, even from the extracted bundle.
    $shortcutMessage = 'Открывайте мастерскую файлом Launch.cmd из распакованной папки Imladris.'
    $desktopShortcut = $false
    try {
        $desktop = [Environment]::GetFolderPath('DesktopDirectory', 'Create')
        New-EditorShortcut $desktop ($title + '.lnk')
        $desktopShortcut = $true
        $shortcutMessage = 'Ярлык «Мастерская Имладриса» добавлен на рабочий стол.'
    }
    catch { [Console]::WriteLine('Desktop shortcut unavailable. Launch.cmd remains available.') }
    if (-not $desktopShortcut) {
        try {
            $programs = [Environment]::GetFolderPath('Programs', 'Create')
            if ([string]::IsNullOrWhiteSpace($programs)) { throw 'Windows не вернула папку меню «Пуск».' }
            New-EditorShortcut (Join-Path $programs 'Imladris') 'Imladris.lnk'
            $shortcutMessage = 'Ярлык Imladris добавлен в меню «Пуск», в папку Imladris.'
        }
        catch { [Console]::WriteLine('Start Menu shortcut unavailable. Launch.cmd remains available.') }
    }
    try { New-EditorShortcut $directory 'Imladris.lnk' }
    catch { [Console]::WriteLine('Local shortcut unavailable. Launch.cmd remains available.') }

    $ready = (Test-Path -LiteralPath (Join-Path $directory 'config.json')) -and
        (Test-Path -LiteralPath (Join-Path $directory 'known_hosts'))
    $completionMarker = Join-Path $directory 'install-completed.txt'
    if ($createdKey -or -not $ready -or -not (Test-Path -LiteralPath $completionMarker -PathType Leaf)) {
        $message = 'Установка завершена. Ваш ключ доступа сохранён.' + "`r`n`r`n" +
            $shortcutMessage + "`r`n" +
            'Если ярлыка нет, откройте Launch.cmd из распакованной папки Imladris.' + "`r`n`r`n" +
            'Сейчас откроется публичный ключ. Отправьте разработчику его текст или файл owner_ed25519.pub. Личный файл owner_ed25519 передавать не нужно.' + "`r`n`r`n" +
            'Если этот ключ уже передан и доступ подтверждён, можно сразу открыть мастерскую. Показать ключ ещё раз можно файлом Show-Key.cmd.'
        $null = [Windows.Forms.MessageBox]::Show($message, $title, 'OK', 'Information')
        Start-Process -FilePath 'notepad.exe' -ArgumentList (ConvertTo-NativeArgument $publicKey)
    }
    else {
        $null = [Windows.Forms.MessageBox]::Show(
            ('Установка обновлена. Ваш ключ доступа сохранён.' + "`r`n`r`n" + $shortcutMessage + "`r`n" +
                'Если ярлыка нет, откройте Launch.cmd из распакованной папки Imladris. Показать публичный ключ можно файлом Show-Key.cmd.'),
            $title, 'OK', 'Information')
    }
    Set-Content -LiteralPath $completionMarker -Value 'Installation completed.' -Encoding ASCII
}
catch {
    $message = $_.Exception.Message
    [Console]::Error.WriteLine('Imladris installation failed:')
    [Console]::Error.WriteLine($message)
    if ($guiReady) {
        try { $null = [Windows.Forms.MessageBox]::Show($message, $title, 'OK', 'Error') }
        catch { [Console]::Error.WriteLine('Unable to display the error dialog. See the error above.') }
    }
    exit 1
}
