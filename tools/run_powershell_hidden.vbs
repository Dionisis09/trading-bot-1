Option Explicit

Dim shell, fileSystem, scriptPath, powershellPath, command, exitCode

If WScript.Arguments.Count <> 1 Then
    WScript.Quit 64
End If

scriptPath = WScript.Arguments(0)
Set fileSystem = CreateObject("Scripting.FileSystemObject")

If Not fileSystem.FileExists(scriptPath) Then
    WScript.Quit 2
End If

Set shell = CreateObject("WScript.Shell")
powershellPath = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe")
command = Quote(powershellPath) & _
    " -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File " & _
    Quote(scriptPath)

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
