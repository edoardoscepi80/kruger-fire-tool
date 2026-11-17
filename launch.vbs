Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = strDir & "\run_app.bat"
WshShell.Run """" & batPath & """", 0, False
Set WshShell = Nothing
Set fso = Nothing
