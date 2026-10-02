Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\PACS"
WshShell.Run """C:\Python311\pythonw.exe"" ""D:\PACS\run_server.py""", 0, False
