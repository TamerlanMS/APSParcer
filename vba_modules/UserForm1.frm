VERSION 5.00
Begin {C62A69F0-16DC-11CE-9E98-00AA00574A4F} UserForm1
   Caption         =   "Выберите наименование"
   ClientHeight    =   5490
   ClientLeft      =   120
   ClientTop       =   465
   ClientWidth     =   7380
   OleObjectBlob   =   "UserForm1.frx":0000
   StartUpPosition =   1  'CenterOwner
End
Attribute VB_Name = "UserForm1"
Attribute VB_Base = "0{5A7A0315-2370-4320-90C3-73A5B85A53CC}{2B7C1DC1-5FD7-47C6-A6DF-367C6C8A8F3F}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = False

' =============================================================================
' UserForm1 — Форма выбора наименования при вводе артикула
'
' Элементы управления:
'   lstMatches — ListBox со списком совпадений "АРТИКУЛ - НАИМЕНОВАНИЕ"
'   btnOK      — Кнопка «ОК» (также Enter)
'   btnCancel  — Кнопка «Отмена» (также Escape)
'
' Использование:
'   frm.lstMatches.AddItem "АРТИКУЛ - Наименование"  ' заполнить список
'   result = frm.GetSelectedValue                      ' показать форму, получить выбор
'   Unload frm
' =============================================================================

Private SelectedValue As String

Private Sub UserForm_Initialize()
    lstMatches.Clear
    SelectedValue = ""
    Me.btnOK.Default = True      ' Enter → OK
    Me.btnCancel.Cancel = True   ' Escape → Отмена
End Sub

' Двойной клик по элементу списка = подтверждение
Private Sub lstMatches_DblClick(ByVal Cancel As MSForms.ReturnBoolean)
    If lstMatches.ListIndex <> -1 Then
        Call btnOK_Click
    End If
End Sub

' Навигация по списку стрелками (без двойного сдвига)
Private Sub lstMatches_KeyDown(ByVal KeyCode As MSForms.ReturnInteger, ByVal Shift As Integer)
    Select Case KeyCode
        Case vbKeyUp
            If lstMatches.ListIndex > 0 Then
                lstMatches.ListIndex = lstMatches.ListIndex - 1
            End If
            KeyCode = 0
        Case vbKeyDown
            If lstMatches.ListIndex < lstMatches.ListCount - 1 Then
                lstMatches.ListIndex = lstMatches.ListIndex + 1
            End If
            KeyCode = 0
    End Select
End Sub

Private Sub btnOK_Click()
    If lstMatches.ListIndex <> -1 Then
        SelectedValue = lstMatches.List(lstMatches.ListIndex)
        Me.Hide
    Else
        MsgBox "Выберите элемент из списка перед нажатием «ОК».", vbExclamation
    End If
End Sub

Private Sub btnCancel_Click()
    SelectedValue = ""
    Me.Hide
End Sub

Private Sub UserForm_QueryClose(Cancel As Integer, CloseMode As Integer)
    If CloseMode = vbFormControlMenu Then
        Cancel = True
        Call btnCancel_Click
    End If
End Sub

' Отображает форму и возвращает выбранное значение (или "" при отмене)
Public Function GetSelectedValue() As String
    If lstMatches.ListCount > 0 Then
        lstMatches.ListIndex = 0
    End If
    lstMatches.SetFocus
    Me.Show
    GetSelectedValue = SelectedValue
End Function
