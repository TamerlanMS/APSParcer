Attribute VB_Name = "вкл_выкл_макрос"
Option Explicit

' =============================================================================
' вкл_выкл_макрос.bas
'
' Управление включением/выключением макроса поиска артикулов.
'
' Горячие клавиши:
'   Ctrl + Q  (английская раскладка)
'   Ctrl + Й  (русская раскладка)
'
' EnableMyMacro — Public-переменная, видна из всех модулей и листов.
' При открытии книги макрос ВЫКЛЮЧЕН (False по умолчанию).
' =============================================================================

' ОБЯЗАТЕЛЬНО Public! Иначе код на листе не узнает, включен макрос или нет
Public EnableMyMacro As Boolean


Sub EnableMacro()
    EnableMyMacro = True
    MsgBox "Макрос включён", vbInformation, "Статус"
End Sub


Sub DisableMacro()
    EnableMyMacro = False
    MsgBox "Макрос отключён", vbInformation, "Статус"
End Sub


' --- Переключатель для АНГЛИЙСКОЙ раскладки (Ctrl + Q) ---
Sub ToggleMacroEng()
Attribute ToggleMacroEng.VB_ProcData.VB_Invoke_Func = "q\n14"
    If EnableMyMacro Then
        Call DisableMacro
    Else
        Call EnableMacro
    End If
End Sub


' --- Переключатель для РУССКОЙ раскладки (Ctrl + Й) ---
Sub ToggleMacroRus()
Attribute ToggleMacroRus.VB_ProcData.VB_Invoke_Func = "й\n14"
    If EnableMyMacro Then
        Call DisableMacro
    Else
        Call EnableMacro
    End If
End Sub
